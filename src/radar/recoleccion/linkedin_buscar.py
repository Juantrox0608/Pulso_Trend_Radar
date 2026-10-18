"""Descubrimiento por citas de Exa y lectura de posts públicos sin sesión."""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import islice
from time import sleep
from urllib.request import Request, urlopen

from radar.contrato import id_contrato, id_desde_url
from radar.recoleccion import imprimir_json, linkedin
from radar.recoleccion.presupuesto_busqueda import PresupuestoBusqueda, LimiteBusqueda

_presupuesto = None


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


def _pedir_busqueda(request):
    global _presupuesto
    if _presupuesto is None:
        _presupuesto = PresupuestoBusqueda.desde_entorno()
    return _presupuesto.llamar(request, _pedir)


def _peticion_groq(mensajes, clave, *, busqueda=False):
    cuerpo = {"model": "openai/gpt-oss-20b", "reasoning_effort": "low",
              "max_completion_tokens": 2000 if busqueda else 6000, "messages": mensajes}
    if busqueda:
        cuerpo.update(tools=[{"type": "browser_search"}], tool_choice="required")
    else:
        cuerpo['temperature'] = 0
    return Request("https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(cuerpo).encode('utf-8'),
        headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json",
                 "User-Agent": "TredRadar/1.0"})


def _urls_groq(valor):
    # executed_tools contiene objetos anidados y, a veces, JSON dentro de cadenas.
    if isinstance(valor, dict):
        for contenido in valor.values():
            yield from _urls_groq(contenido)
    elif isinstance(valor, list):
        for contenido in valor:
            yield from _urls_groq(contenido)
    elif isinstance(valor, str):
        for url in re.findall(r'https?://[^\s<>"\\]+', valor):
            yield url.rstrip('.,;:!?)]}')


def _filtrar_urls(candidatas, validar_url, max_resultados):
    urls, vistos = [], set()
    for url in candidatas:
        try:
            validar_url(url)
            identificador = id_contrato(*id_desde_url(url))
        except (TypeError, ValueError, AttributeError):
            continue
        if identificador not in vistos:
            vistos.add(identificador)
            urls.append(url)
            if len(urls) == max_resultados:
                break
    return urls


def buscar_urls(consulta, *, clave, max_resultados=10, pedir=None,
                dominio="linkedin.com", validar_url=_validar_post, resumen=None):
    """Devuelve (URLs únicas de posts, costo USD); pedir recibe un Request y devuelve JSON."""
    _entero(max_resultados, 1, 10, "max_resultados")
    if not isinstance(consulta, str) or not consulta.strip():
        raise ValueError("La consulta debe contener texto")
    clave_groq = os.environ.get('GROQ_API_KEY', '').strip()
    if not (clave and clave.strip()) and not clave_groq:
        raise ValueError("Falta OPENROUTER_API_KEY en el entorno")
    detalle = resumen if resumen is not None else {}
    costo = Decimal('0')
    cuerpo = {
        "model": "deepseek/deepseek-v4-flash-0731", "reasoning": {"enabled": False}, "max_tokens": 300,
        "plugins": [{"id": "web", "engine": "exa", "max_results": max_resultados,
                     "include_domains": [dominio], "search_prompt": "Resultados:"}],
        "messages": [{"role": "user", "content": consulta.strip()}],
    }
    try:
        if not clave or not clave.strip():
            raise ValueError()
        request = Request("https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(cuerpo).encode("utf-8"),
            headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json"})
        respuesta = (pedir or _pedir_busqueda)(request)
        importe = Decimal(str(respuesta["usage"]["cost"]))
        if not importe.is_finite() or importe < 0:
            raise ValueError()
        costo = importe
        anotaciones = respuesta["choices"][0]["message"]["annotations"]
        if not isinstance(anotaciones, list):
            raise ValueError()
        candidatas = [a['url_citation'].get('url') for a in anotaciones
                      if isinstance(a, dict) and isinstance(a.get('url_citation'), dict)]
        urls = _filtrar_urls(candidatas, validar_url, max_resultados)
        detalle.update(proveedor='openrouter', groq_tokens=0)
        return urls, costo
    except LimiteBusqueda:
        if not clave_groq:
            raise
    except Exception:
        # El proveedor puede incluir credenciales, consultas o nombres en sus errores.
        if not clave_groq:
            raise ValueError("OpenRouter: no se pudo obtener una respuesta de búsqueda válida") from None
    try:
        prompt = (f'Busca en la web publicaciones públicas de {dominio} sobre esta consulta: {consulta.strip()}. '
                  f'Devuelve solo URLs completas de publicaciones de {dominio}, una por línea.')
        request = _peticion_groq([{'role': 'user', 'content': prompt}], clave_groq, busqueda=True)
        respuesta = (pedir or _pedir)(request)
        mensaje = respuesta['choices'][0]['message']
        texto, herramientas = mensaje.get('content'), mensaje.get('executed_tools')
        if not isinstance(texto, str) and not isinstance(herramientas, list):
            raise ValueError()
        tokens = respuesta['usage']['total_tokens']
        if type(tokens) is not int or tokens < 0:
            raise ValueError()
        urls = _filtrar_urls(_urls_groq([herramientas, texto]), validar_url, max_resultados)
        detalle.update(proveedor='groq', groq_tokens=tokens)
        return urls, costo
    except Exception:
        raise ValueError('OpenRouter/Groq: no se pudo obtener una respuesta de búsqueda válida') from None


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
    if not (clave and clave.strip()) and not os.environ.get('GROQ_API_KEY', '').strip():
        raise ValueError("Falta OPENROUTER_API_KEY en el entorno")
    if not sal or not sal.strip():
        raise ValueError("Falta AUTOR_HASH_SAL en el entorno")
    resumen = {"consultas": 0, "consultas_fallidas": 0, "urls": 0, "completados": 0, "omitidos": 0,
               "fuera_fecha": 0, "costo_usd": Decimal("0"), "aviso": None,
               "proveedores": [], "groq_tokens": 0}
    urls, vistos = [], set()
    for consulta in consultas:
        if dias is not None:
            meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                     "septiembre", "octubre", "noviembre", "diciembre")
            consulta = (f"publicaciones de los últimos {dias} días ({meses[ahora.month - 1]} de {ahora.year}) "
                        f"en LinkedIn: {consulta}")
        resumen["consultas"] += 1
        detalle = {'consulta': resumen['consultas'], 'proveedor': None, 'groq_tokens': 0}
        resumen['proveedores'].append(detalle)
        try:
            encontradas, costo = buscar_urls(consulta, clave=clave, max_resultados=max_resultados,
                                            pedir=pedir, resumen=detalle)
        except LimiteBusqueda as error:
            resumen['consultas_fallidas'] += 1
            if resumen['consultas'] == resumen['consultas_fallidas']:
                raise
            resumen['aviso'] = str(error)
            break
        except ValueError:
            resumen["consultas_fallidas"] += 1
            continue
        resumen["costo_usd"] += costo
        resumen['groq_tokens'] += detalle['groq_tokens']
        for url in encontradas:
            identificador = id_contrato(*id_desde_url(url))
            if identificador not in vistos:
                vistos.add(identificador)
                urls.append(url)
    if resumen["consultas_fallidas"] == resumen["consultas"]:
        raise ValueError("OpenRouter/Groq: no se pudo obtener una respuesta de búsqueda válida en ninguna consulta")
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
    print(f"Proveedores por consulta: {resumen['proveedores']}; tokens Groq: {resumen['groq_tokens']}", file=sys.stderr)
    if resumen["aviso"]:
        print(resumen["aviso"], file=sys.stderr)


if __name__ == "__main__":
    main()
