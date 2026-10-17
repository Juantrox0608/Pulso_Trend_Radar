"""Importa publicaciones manuales sin persistir autores ni enlaces originales."""
import argparse
import csv
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import ValidationError

from radar.contrato import Publicacion, calcular_autor_hash, id_contrato, id_desde_url

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
    autor = d.get("autor", "")
    if not autor:
        ruta = unquote(urlsplit(url).path)
        patron = r"/@([^/]+)/video/" if plataforma.value == "tiktok" else r"/posts/([^/_]+)_"
        coincidencia = re.search(patron, ruta)
        autor = coincidencia.group(1) if coincidencia else ""
    if not autor:
        raise ValueError("autor: completa la columna; no aparece en el enlace")

    fecha = d["fecha_publicacion"]
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
        raise ValueError("fecha_publicacion: usa AAAA-MM-DD, DD/MM/AAAA o fecha ISO con zona horaria") from None

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
        texto=d["texto"], formato=formato, duracion_segundos=duracion,
        tipo_autor=(d.get("tipo_autor") or "desconocido").split()[0],
        idioma=idioma or None, pais=pais,
        hashtags=tuple(filter(None, re.split(r"[\s,]+", d.get("hashtags", "")))),
        autor_hash=calcular_autor_hash(plataforma, autor, sal),
        publicada_en=publicada, capturada_en=ahora, origen="csv_manual",
    )


def leer_publicaciones(ruta: str | Path) -> list[Publicacion]:
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
        separador = csv.Sniffer().sniff(encabezado, delimiters=",;").delimiter
    except csv.Error:
        raise ValueError("CSV: encabezado inválido; usa columnas separadas por coma o punto y coma") from None
    reader = csv.DictReader(StringIO(contenido, newline=""), delimiter=separador, strict=True)
    nombres = reader.fieldnames or []
    faltan = _OBLIGATORIAS - set(nombres)
    if faltan:
        raise ValueError("CSV: faltan columnas obligatorias: " + ", ".join(sorted(faltan)))
    if len(nombres) != len(set(nombres)):
        raise ValueError("CSV: hay encabezados duplicados")
    errores, publicaciones = [], []
    ahora = datetime.now(timezone.utc)
    try:
        while True:
            linea = reader.line_num + 1
            fila = next(reader, None)
            if fila is None:
                break
            if all(isinstance(v, str) and not v.strip() for v in fila.values()):
                continue
            try:
                publicaciones.append(_publicacion(fila, sal, ahora))
            except ValidationError as error:
                campos = sorted({str(e["loc"][0]) for e in error.errors()})
                errores.append(f"Línea {linea}: valor inválido en " + ", ".join(campos))
            except ValueError as error:
                errores.append(f"Línea {linea}: {error}")
    except csv.Error:
        errores.append(f"Línea {reader.line_num}: estructura CSV inválida; revisa comillas y separadores")
    if errores:
        raise ValueError("CSV inválido; no se importó ninguna publicación:\n" + "\n".join(errores)) from None
    return publicaciones


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Importa publicaciones públicas desde un CSV manual.")
    parser.add_argument("csv")
    args = parser.parse_args(argv)
    try:
        publicaciones = leer_publicaciones(args.csv)
    except ValueError as error:
        parser.exit(1, f"Error: {error}\n")
    except OSError:
        parser.exit(1, "Error: no se pudo leer el CSV; revisa la ruta y permisos.\n")
    print(json.dumps([p.model_dump(mode="json") for p in publicaciones], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
