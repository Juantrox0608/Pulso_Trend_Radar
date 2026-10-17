"""Descubrimiento por citas de Exa y lectura de posts públicos sin sesión."""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import islice
from time import sleep
from urllib.request import Request, urlopen

from radar.contrato import id_contrato, id_desde_url
from radar.recoleccion import imprimir_json, linkedin


def _fecha_desde_id(identificador):
    if identificador.isdecimal():
        try:
            return datetime.fromtimestamp((int(identificador) >> 22) / 1000, timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    return None


def _entero(valor, minimo, maximo, nombre):
    if type(valor) is not int or not minimo <= valor <= maximo:
        raise ValueError(f"{nombre} debe estar entre {minimo} y {maximo}")


def _consultas(consultas):
    if isinstance(consultas, str):
        raise ValueError("consultas debe ser una lista de consultas")
    consultas = list(islice(consultas, 21))
    if not 1 <= len(consultas) <= 20:
        raise ValueError("Se permiten entre 1 y 20 consultas por corrida")
    if any(not isinstance(c, str) or not c.strip() for c in consultas):
        raise ValueError("Cada consulta debe contener texto")
    return consultas


def _pedir(request):
    with urlopen(request, timeout=20) as respuesta:
        return json.load(respuesta)


def _validar_post(url):
    linkedin._validar_url(url, final=True)


def buscar_urls(consulta, *, clave, max_resultados=10, pedir=None,
                dominio="linkedin.com", validar_url=_validar_post):
    """Devuelve (URLs únicas de posts, costo USD); pedir recibe un Request y devuelve JSON."""
    _entero(max_resultados, 1, 10, "max_resultados")
    if not isinstance(consulta, str) or not consulta.strip():
        raise ValueError("La consulta debe contener texto")
    if not clave or not clave.strip():
        raise ValueError("Falta OPENROUTER_API_KEY en el entorno")
    cuerpo = {
        "model": "deepseek/deepseek-v4-flash-0731", "reasoning": {"enabled": False}, "max_tokens": 300,
        "plugins": [{"id": "web", "engine": "exa", "max_results": max_resultados,
                     "include_domains": [dominio], "search_prompt": "Resultados:"}],
        "messages": [{"role": "user", "content": consulta.strip()}],
    }
    try:
        request = Request("https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(cuerpo).encode("utf-8"),
            headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json"})
        respuesta = (pedir or _pedir)(request)
        anotaciones = respuesta["choices"][0]["message"]["annotations"]
        costo = Decimal(str(respuesta["usage"]["cost"]))
        if not isinstance(anotaciones, list) or not costo.is_finite() or costo < 0:
            raise ValueError()
        urls, vistos = [], set()
        for anotacion in anotaciones:
            try:
                url = anotacion["url_citation"]["url"]
                validar_url(url)
                identificador = id_contrato(*id_desde_url(url))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if identificador not in vistos:
                vistos.add(identificador)
                urls.append(url)
                if len(urls) == max_resultados:
                    break
        return urls, costo
    except Exception:
        # El proveedor puede incluir credenciales, consultas o nombres en sus errores.
        raise ValueError("OpenRouter: no se pudo obtener una respuesta de búsqueda válida") from None


def descubrir(consultas, *, clave, sal, dias=None, maximo=100, pedir=None, obtener=None,
              pausa=sleep, max_resultados=10):
    """Devuelve (publicaciones, métricas, resumen); los bloqueos conservan lo ya reunido."""
    consultas = _consultas(consultas)
    _entero(maximo, 1, 100, "maximo")
    _entero(max_resultados, 1, 10, "max_resultados")
    ahora = datetime.now(timezone.utc)
    desde = None
    if dias is not None:
        _entero(dias, 1, 3652058, "dias")
        try:
            desde = ahora - timedelta(days=dias)
        except OverflowError:
            raise ValueError("dias excede el intervalo de fechas permitido") from None
    if not clave or not clave.strip():
        raise ValueError("Falta OPENROUTER_API_KEY en el entorno")
    if not sal or not sal.strip():
        raise ValueError("Falta AUTOR_HASH_SAL en el entorno")
    resumen = {"consultas": 0, "consultas_fallidas": 0, "urls": 0, "completados": 0, "omitidos": 0,
               "fuera_fecha": 0, "costo_usd": Decimal("0"), "aviso": None}
    urls, vistos = [], set()
    for consulta in consultas:
        if dias is not None:
            meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                     "septiembre", "octubre", "noviembre", "diciembre")
            consulta = (f"publicaciones de los últimos {dias} días ({meses[ahora.month - 1]} de {ahora.year}) "
                        f"en LinkedIn: {consulta}")
        resumen["consultas"] += 1
        try:
            encontradas, costo = buscar_urls(consulta, clave=clave, max_resultados=max_resultados, pedir=pedir)
        except ValueError:
            resumen["consultas_fallidas"] += 1
            continue
        resumen["costo_usd"] += costo
        for url in encontradas:
            identificador = id_contrato(*id_desde_url(url))
            if identificador not in vistos:
                vistos.add(identificador)
                urls.append(url)
    if resumen["consultas_fallidas"] == resumen["consultas"]:
        raise ValueError("OpenRouter: no se pudo obtener una respuesta de búsqueda válida en ninguna consulta")
    resumen["urls"] = len(urls)
    if desde is not None:
        recientes = []
        for url in urls:
            fecha = _fecha_desde_id(id_desde_url(url)[1])
            if fecha is not None and fecha < desde:
                resumen["fuera_fecha"] += 1
            else:
                recientes.append(url)
        urls = recientes
    publicaciones, metricas = [], []
    reunidos = set()
    for intento, url in enumerate(urls[:maximo]):
        if intento:
            pausa(3)
        try:
            publicacion, metrica = linkedin.recolectar(url, sal=sal, obtener=obtener)
        except linkedin.BloqueoLinkedIn:
            resumen["aviso"] = "Bloqueo de LinkedIn: consultas a posts detenidas sin reintentos; salida parcial."
            break
        except ValueError:
            resumen["omitidos"] += 1
            continue
        resumen["completados"] += 1
        if desde is not None and publicacion.publicada_en < desde:
            resumen["fuera_fecha"] += 1
            continue
        # Una redirección puede revelar que dos URLs correspondían al mismo post.
        if publicacion.id in reunidos:
            continue
        reunidos.add(publicacion.id)
        publicaciones.append(publicacion)
        if metrica is not None:
            metricas.append(metrica)
    return publicaciones, metricas, resumen


def main(argv=None):
    parser = argparse.ArgumentParser(description="Descubre posts de LinkedIn por tema con Exa y devuelve JSON.")
    parser.add_argument("--consulta", action="append", required=True, help="Repetible, máximo 20 consultas")
    parser.add_argument("--dias", type=int, help="Conservar posts publicados en los últimos N días")
    parser.add_argument("--max", dest="maximo", type=int, default=100, help="Máximo de posts a consultar (1–100)")
    parser.add_argument("--resultados", type=int, default=10, help="Resultados por consulta (1–10)")
    args = parser.parse_args(argv)
    try:
        publicaciones, metricas, resumen = descubrir(args.consulta,
            clave=os.environ.get("OPENROUTER_API_KEY", ""), sal=os.environ.get("AUTOR_HASH_SAL", ""),
            dias=args.dias, maximo=args.maximo, max_resultados=args.resultados)
    except ValueError as error:
        parser.exit(1, f"Error: {error}\n")
    imprimir_json(publicaciones, metricas)
    print(f"Consultas: {resumen['consultas']}; consultas fallidas: {resumen['consultas_fallidas']}; "
          f"URLs encontradas (únicas): {resumen['urls']}; "
          f"posts completados: {resumen['completados']}; omitidos: {resumen['omitidos']}; "
          f"fuera de fecha: {resumen['fuera_fecha']}; costo total: USD {resumen['costo_usd']:.6f}", file=sys.stderr)
    if resumen["aviso"]:
        print(resumen["aviso"], file=sys.stderr)


if __name__ == "__main__":
    main()
