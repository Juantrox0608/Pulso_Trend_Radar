"""YouTube Data API: una búsqueda y un lote de detalles, sin persistir autores."""

import argparse
import json
import os
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from radar.contrato import (
    Formato, Metrica, Origen, Plataforma, Publicacion, TipoAutor,
    calcular_autor_hash, id_contrato,
)
from radar.recoleccion import sin_autor, imprimir_json, segundos_iso8601 as _segundos

Peticion = Callable[[str, dict], dict]


def _pedir_json(recurso: str, parametros: dict) -> dict:
    url = "https://www.googleapis.com/youtube/v3/" + recurso + "?" + urlencode(parametros)
    try:
        with urlopen(url, timeout=30) as respuesta:
            return json.load(respuesta)
    except HTTPError as error:
        raise RuntimeError(f"YouTube rechazó la petición (HTTP {error.code}); revisa clave y cuota.") from None
    except (URLError, OSError):
        raise RuntimeError("No se pudo conectar con YouTube; revisa la conexión e intenta de nuevo.") from None
    except (ValueError, UnicodeError):
        raise RuntimeError("YouTube devolvió una respuesta JSON inválida.") from None


def buscar_con_metricas(
    consulta: str,
    pais: str,
    idioma: str,
    desde: datetime,
    *,
    max_resultados: int = 50,
    peticion: Peticion = _pedir_json,
) -> tuple[list[Publicacion], list[Metrica]]:
    """Devuelve hasta 50 publicaciones; peticion(recurso, parametros) permite probar sin red.

    El país corresponde a la búsqueda, no a la ubicación del autor. El idioma se
    toma del video y puede faltar o diferir del idioma solicitado en la búsqueda.
    """
    pais = pais.strip().upper()
    idioma = idioma.strip().lower()
    if not consulta.strip():
        raise ValueError("La consulta no puede estar vacía")
    if not re.fullmatch(r"[A-Z]{2}", pais) or not re.fullmatch(r"[a-z]{2}", idioma):
        raise ValueError("Usa país de dos letras (MX) e idioma de dos letras (es)")
    if desde.tzinfo is None or desde.utcoffset() is None:
        raise ValueError("La fecha desde debe incluir zona horaria")
    if not 1 <= max_resultados <= 50:
        raise ValueError("max_resultados debe estar entre 1 y 50")
    clave = os.environ.get("YOUTUBE_API_KEY")
    sal = os.environ.get("AUTOR_HASH_SAL")
    if not clave:
        raise ValueError("Falta la variable de entorno YOUTUBE_API_KEY")
    if not sal:
        raise ValueError("Falta la variable de entorno AUTOR_HASH_SAL")

    def pedir(recurso, parametros):
        respuesta = peticion(recurso, {**parametros, "key": clave})
        if not isinstance(respuesta, dict) or "error" in respuesta:
            raise RuntimeError("YouTube devolvió un error; revisa clave y cuota.")
        return respuesta

    busqueda = pedir("search", {
        "part": "snippet", "type": "video", "q": consulta.strip(),
        "regionCode": pais, "relevanceLanguage": idioma,
        "publishedAfter": desde.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "maxResults": max_resultados, "fields": "items(id/videoId)",
    })
    try:
        ids = list(dict.fromkeys(item["id"]["videoId"] for item in busqueda["items"]))[:max_resultados]
        for id_nativo in ids:
            id_contrato(Plataforma.YOUTUBE, id_nativo)
    except (KeyError, TypeError, ValueError):
        raise ValueError("Respuesta de búsqueda de YouTube inválida") from None
    if not ids:
        return [], []
    videos = pedir("videos", {
        "part": "snippet,contentDetails,statistics", "id": ",".join(ids),
        "fields": "items(id,snippet(title,description,tags,publishedAt,channelId,channelTitle,defaultAudioLanguage,defaultLanguage,liveBroadcastContent),contentDetails/duration,statistics(viewCount,likeCount,commentCount))",
    })
    capturada_en = datetime.now(timezone.utc)
    publicaciones = []
    metricas = []
    try:
        for video in videos["items"]:
            if video["id"] not in ids:
                raise ValueError("Video ajeno a la búsqueda")
            snippet = video["snippet"]
            # En vivo o programado: todavía no es una pieza publicada con métricas reales.
            if snippet.get("liveBroadcastContent", "none") != "none":
                continue
            segundos = _segundos(video["contentDetails"]["duration"])
            # shortcut: <=180 s aproxima video corto; usar metadata de Shorts cuando esté disponible.
            formato = Formato.VIDEO_CORTO if segundos <= 180 else Formato.VIDEO_LARGO
            publicaciones.append(Publicacion(
                id=id_contrato(Plataforma.YOUTUBE, video["id"]),
                plataforma=Plataforma.YOUTUBE,
                titulo=snippet["title"], texto=snippet.get("description", "")[:5000],
                # channelTitle se usa solo aquí, para no guardar el nombre del canal como etiqueta.
                hashtags=sin_autor(snippet.get("tags", ()), snippet.get("channelTitle", "")), formato=formato,
                duracion_segundos=segundos,
                idioma=snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage"),
                pais=pais, tipo_autor=TipoAutor.DESCONOCIDO,
                autor_hash=calcular_autor_hash(Plataforma.YOUTUBE, snippet["channelId"], sal),
                publicada_en=snippet["publishedAt"], capturada_en=capturada_en,
                origen=Origen.API_OFICIAL,
            ))
            estadisticas = video.get("statistics", {})
            if not isinstance(estadisticas, dict):
                raise ValueError("Estadísticas inválidas")
            conteos = {}
            for campo, externo in (("vistas", "viewCount"), ("likes", "likeCount"), ("comentarios", "commentCount")):
                valor = estadisticas.get(externo)
                if valor is not None:
                    if isinstance(valor, bool) or not re.fullmatch(r"[0-9]+", str(valor)):
                        raise ValueError("Estadística inválida")
                    conteos[campo] = int(valor)
            if conteos:
                metricas.append(Metrica(publicacion_id=publicaciones[-1].id,
                    capturada_en=capturada_en, origen=Origen.API_OFICIAL, **conteos))
    except (KeyError, TypeError, ValueError):
        raise ValueError("Metadatos de video de YouTube inválidos para el contrato") from None
    return publicaciones, metricas


def buscar_publicaciones(
    consulta: str, pais: str, idioma: str, desde: datetime, *,
    max_resultados: int = 50, peticion: Peticion = _pedir_json,
) -> list[Publicacion]:
    """Compatibilidad: devuelve solo las publicaciones de la captura."""
    return buscar_con_metricas(consulta, pais, idioma, desde,
        max_resultados=max_resultados, peticion=peticion)[0]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Busca videos públicos de YouTube y devuelve JSON.")
    parser.add_argument("consulta")
    parser.add_argument("--pais", default="MX")
    parser.add_argument("--idioma", default="es")
    parser.add_argument("--dias", type=int, default=7)
    args = parser.parse_args(argv)
    if args.dias < 1:
        parser.error("--dias debe ser mayor que cero")
    try:
        desde = datetime.now(timezone.utc) - timedelta(days=args.dias)
        publicaciones, metricas = buscar_con_metricas(args.consulta, args.pais, args.idioma, desde)
    except (ValueError, RuntimeError, OverflowError) as error:
        parser.exit(1, f"Error: {error}\n")
    imprimir_json(publicaciones, metricas)


if __name__ == "__main__":
    main()
