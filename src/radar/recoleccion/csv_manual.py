"""Importa publicaciones manuales sin persistir autores ni enlaces originales."""
import argparse
import csv
import os
import re
import unicodedata
from time import sleep
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import ValidationError

from radar.contrato import Metrica, Publicacion, calcular_autor_hash, id_contrato, id_desde_url
from radar.recoleccion import sin_autor, reparar_texto, imprimir_json
from radar.recoleccion.linkedin import BloqueoLinkedIn

_OBLIGATORIAS = {"url", "fecha_publicacion", "texto", "formato"}
_PAISES = dict(zip(
    ("mexico", "colombia", "argentina", "peru", "chile", "brasil", "espana", "estados unidos"),
    ("MX", "CO", "AR", "PE", "CL", "BR", "ES", "US"),
))
_IDIOMAS = {"espanol": "es", "ingles": "en", "portugues": "pt"}


def _etiqueta(valor: str) -> str:
    # Excel puede mezclar etiquetas UTF-8 mal decodificadas con Windows-1252.
    try:
        valor = valor.encode("cp1252").decode("utf-8")
    except (UnicodeError, ValueError):
        pass
    return "".join(c for c in unicodedata.normalize("NFD", valor.casefold()) if not unicodedata.combining(c))


def _url_permitida(url: str) -> None:
    try:
        p = urlsplit(url)
        puerto = p.port
    except ValueError:
        raise ValueError("url: estructura o puerto inválido") from None
    if "://" in p.path:
        raise ValueError("url: hay varios enlaces pegados; deja solo uno")
    host = (p.hostname or "").lower()
    dominios = ("lnkd.in", "linkedin.com", "tiktok.com")
    if (p.scheme != "https" or p.username or p.password or puerto not in (None, 443)
            or not any(host == d or (d != "lnkd.in" and host.endswith("." + d)) for d in dominios)):
        raise ValueError("url: usa un enlace HTTPS de TikTok o LinkedIn")


def _fecha(fecha: str, campo: str) -> datetime:
    try:
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", fecha):
            publicada = datetime.strptime(fecha, "%d/%m/%Y").replace(tzinfo=timezone.utc)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha):
            # shortcut: sin hora se usa 00:00 UTC; pedir hora exacta al medir velocidad intradía.
            publicada = datetime.fromisoformat(fecha).replace(tzinfo=timezone.utc)
        else:
            publicada = datetime.fromisoformat(fecha)
            if publicada.utcoffset() is None:
                raise ValueError()
    except ValueError:
        raise ValueError(f"{campo}: usa AAAA-MM-DD, DD/MM/AAAA o fecha ISO con zona horaria") from None

    return publicada


def _publicacion(fila: dict, sal: str, ahora: datetime) -> Publicacion:
    if None in fila or any(v is None for v in fila.values()):
        raise ValueError("columnas: cantidad de celdas distinta al encabezado")
    d = {k: v.strip() for k, v in fila.items()}
    for campo in sorted(_OBLIGATORIAS):
        if not d[campo]:
            raise ValueError(f"{campo}: campo obligatorio vacío")
    url = d["url"]
    _url_permitida(url)
    identificable = url
    partes = urlsplit(url)
    if (partes.hostname or "").lower().endswith("linkedin.com"):
        destacado = parse_qs(partes.query).get("highlightedUpdateUrn", [""])[0]
        actividad = re.fullmatch(r"urn:li:activity:(\d{15,22})", destacado)
        if actividad:
            identificable = "https://www.linkedin.com/feed/update/urn:li:activity:" + actividad.group(1) + "/"
    try:
        plataforma, nativo = id_desde_url(identificable)
    except ValueError:
        raise ValueError("url: no contiene un identificador de publicación válido; copia el enlace completo") from None
    ruta = unquote(urlsplit(url).path)
    patron = r"/@([^/]+)/video/" if plataforma.value == "tiktok" else r"/posts/([^/_]+)_"
    coincidencia = re.search(patron, ruta)
    del_enlace = coincidencia.group(1) if coincidencia else ""
    autor = d.get("autor", "") or del_enlace
    if not autor:
        raise ValueError("autor: completa la columna; no aparece en el enlace")

    publicada = _fecha(d["fecha_publicacion"], "fecha_publicacion")

    formato = d["formato"]
    duracion = None
    video = re.fullmatch(r"video (\d+)s", formato)
    if video:
        duracion = int(video.group(1))
        # shortcut: <=180 s aproxima video corto; confirmar formato con metadata cuando exista.
        formato = "video_corto" if duracion <= 180 else "video_largo"
    idioma = _etiqueta(d.get("idioma", ""))
    idioma = _IDIOMAS.get(idioma, idioma)
    if idioma and not re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)*", idioma):
        raise ValueError("idioma: usa código de dos letras o español, inglés o portugués")
    pais = _etiqueta(d.get("pais", ""))
    pais = None if pais in ("", "n/d") else _PAISES.get(pais, pais.upper())
    return Publicacion(
        id=id_contrato(plataforma, nativo), plataforma=plataforma,
        texto=reparar_texto(d["texto"]), formato=formato, duracion_segundos=duracion,
        tipo_autor=(d.get("tipo_autor") or "desconocido").split()[0],
        idioma=idioma or None, pais=pais,
        hashtags=sin_autor(filter(None, re.split(r"[\s,]+", d.get("hashtags", ""))), autor, del_enlace),
        autor_hash=calcular_autor_hash(plataforma, autor, sal),
        publicada_en=publicada, capturada_en=ahora, origen="csv_manual",
    )


def _numero(valor: str, campo: str) -> int | None:
    valor = valor.strip()
    if not valor:
        return None
    error = f"{campo}: usa un entero, miles con punto o una cantidad exacta con K/mil/M"
    if len(valor) > 64:
        raise ValueError(error)
    if re.fullmatch(r"[0-9]+", valor):
        return int(valor)
    if re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{3})+", valor):
        return int(valor.replace(".", ""))
    abreviado = re.fullmatch(r"([0-9]+)(?:[.,]([0-9]+))?\s*(k|mil|m)", valor, flags=re.IGNORECASE)
    if not abreviado:
        raise ValueError(error)
    entero, fraccion, sufijo = abreviado.groups()
    fraccion = fraccion or ""
    factor = 1000000 if sufijo.lower() == "m" else 1000
    resultado, resto = divmod(int(entero + fraccion) * factor, 10 ** len(fraccion))
    if resto:
        raise ValueError(error)
    return resultado


def leer_con_metricas(ruta: str | Path, *, completar_tiktok=False, completar_linkedin=False, pausa=sleep) -> tuple[list[Publicacion], list[Metrica]]:
    """Valida el CSV completo; si alguna fila falla no devuelve resultados parciales."""
    sal = os.environ.get("AUTOR_HASH_SAL")
    if not sal or not sal.strip():
        raise ValueError("Falta la variable de entorno AUTOR_HASH_SAL")
    try:
        contenido = Path(ruta).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            contenido = Path(ruta).read_text(encoding="cp1252")
        except UnicodeDecodeError:
            raise ValueError("CSV: codificación inválida; guarda como UTF-8") from None
    encabezado = contenido.splitlines()[0] if contenido else ""
    try:
        separador = "," if encabezado.strip() == "url" else csv.Sniffer().sniff(encabezado, delimiters=",;").delimiter
    except csv.Error:
        raise ValueError("CSV: encabezado inválido; usa columnas separadas por coma o punto y coma") from None
    reader = csv.DictReader(StringIO(contenido, newline=""), delimiter=separador, strict=True)
    nombres = reader.fieldnames or []
    faltan = ({"url"} if completar_tiktok or completar_linkedin else _OBLIGATORIAS) - set(nombres)
    if faltan:
        raise ValueError("CSV: faltan columnas obligatorias: " + ", ".join(sorted(faltan)))
    if len(nombres) != len(set(nombres)):
        raise ValueError("CSV: hay encabezados duplicados")
    errores, publicaciones, metricas = [], [], []
    captura_archivo = datetime.fromtimestamp(Path(ruta).stat().st_mtime, timezone.utc)
    filas = []
    try:
        while True:
            linea = reader.line_num + 1
            fila = next(reader, None)
            if fila is None:
                break
            if all(isinstance(v, str) and not v.strip() for v in fila.values()):
                continue
            filas.append((linea, fila))
    except csv.Error:
        errores.append(f"Línea {reader.line_num}: estructura CSV inválida; revisa comillas y separadores")
    def automatico(fila):
        host = urlsplit((fila.get("url") or "").strip()).hostname or ""
        if completar_tiktok and (host == "tiktok.com" or host.endswith(".tiktok.com")):
            return "tiktok"
        if completar_linkedin and (host == "lnkd.in" or host == "linkedin.com" or host.endswith(".linkedin.com")):
            return "linkedin"
        return None

    cantidades = {"tiktok": 0, "linkedin": 0}
    for _, fila in filas:
        try:
            plataforma = automatico(fila)
        except ValueError:
            continue  # El validador de fila detalla el error sin exponer su contenido.
        if plataforma:
            cantidades[plataforma] += 1
    for plataforma, cantidad in cantidades.items():
        if cantidad > 100:
            raise ValueError(f"{plataforma}: máximo 100 publicaciones por corrida")
    intentos = {"tiktok": 0, "linkedin": 0}
    for indice, (linea, fila) in enumerate(filas):
        try:
            if None in fila or any(v is None for v in fila.values()):
                raise ValueError("columnas: cantidad de celdas distinta al encabezado")
            url = (fila.get("url") or "").strip()
            _url_permitida(url)
            plataforma = automatico(fila)
            if plataforma:
                from radar.recoleccion import tiktok, linkedin
                recolector = tiktok if plataforma == "tiktok" else linkedin
                if intentos[plataforma]:
                    pausa(1.5 if plataforma == "tiktok" else 3)
                intentos[plataforma] += 1
                idioma = _etiqueta(fila.get("idioma", "").strip())
                pais = _etiqueta(fila.get("pais", "").strip())
                p, m = recolector.recolectar(url, sal=sal,
                    texto=fila.get("texto", "").strip() or None,
                    publicada_en=_fecha(fila["fecha_publicacion"].strip(), "fecha_publicacion") if fila.get("fecha_publicacion", "").strip() else None,
                    tipo_autor=(fila.get("tipo_autor", "").strip() or "desconocido").split()[0],
                    idioma=_IDIOMAS.get(idioma, idioma) or None,
                    pais=None if pais in ("", "n/d") else _PAISES.get(pais, pais.upper()),
                    **({"formato": fila.get("formato", "").strip() or None} if plataforma == "linkedin" else {}))
                publicaciones.append(p)
                if m is not None:
                    metricas.append(m)
                continue
            faltan = _OBLIGATORIAS - set(fila)
            if faltan:
                raise ValueError("faltan columnas obligatorias: " + ", ".join(sorted(faltan)))
            fecha_captura = (fila.get("fecha_captura") or "").strip()
            conteos = {campo: _numero(fila.get(columna) or "", columna)
                for campo, columna in (("vistas", "vistas"), ("likes", "reacciones"),
                                       ("comentarios", "comentarios"), ("compartidos", "compartidos"))}
            hay_metricas = any(v is not None for v in conteos.values())
            if hay_metricas and not fecha_captura:
                # La fecha de modificación cambia al editar el CSV y fecharía mal métricas viejas.
                raise ValueError("fecha_captura: obligatoria si anotas métricas; pon el día en que viste los números")
            captura = _fecha(fecha_captura, "fecha_captura") if fecha_captura else captura_archivo
            publicacion = _publicacion(fila, sal, captura)
            if hay_metricas:
                metricas.append(Metrica(publicacion_id=publicacion.id,
                    capturada_en=publicacion.capturada_en, origen=publicacion.origen, **conteos))
            publicaciones.append(publicacion)
        except BloqueoLinkedIn as error:
            errores.append(f"Línea {linea}: {error}")
            pendientes = ", ".join(str(n) for n, _ in filas[indice:])
            errores.append("Corrida detenida; filas sin completar: " + pendientes)
            break
        except ValidationError as error:
            campos = sorted({str(e["loc"][0]) if e["loc"] else "metricas" for e in error.errors()})
            errores.append(f"Línea {linea}: valor inválido en " + ", ".join(campos))
        except ValueError as error:
            errores.append(f"Línea {linea}: {error}")
    if errores:
        raise ValueError("CSV inválido; no se importó ninguna publicación:\n" + "\n".join(errores)) from None
    return publicaciones, metricas


def leer_publicaciones(ruta: str | Path) -> list[Publicacion]:
    """Compatibilidad: devuelve solo las publicaciones de la captura."""
    return leer_con_metricas(ruta)[0]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Importa publicaciones públicas desde un CSV manual.")
    parser.add_argument("csv")
    parser.add_argument("--completar-tiktok", action="store_true", help="Consultar metadatos públicos de TikTok (no oficial)")
    parser.add_argument("--completar-linkedin", action="store_true", help="Consultar la página pública de LinkedIn (no oficial)")
    args = parser.parse_args(argv)
    try:
        publicaciones, metricas = leer_con_metricas(args.csv, completar_tiktok=args.completar_tiktok, completar_linkedin=args.completar_linkedin)
    except ValueError as error:
        parser.exit(1, f"Error: {error}\n")
    except OSError:
        parser.exit(1, "Error: no se pudo leer el CSV; revisa la ruta y permisos.\n")
    imprimir_json(publicaciones, metricas)


if __name__ == "__main__":
    main()
