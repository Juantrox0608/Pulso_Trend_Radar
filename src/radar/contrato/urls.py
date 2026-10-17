"""URLs canónicas sin datos del autor, y extracción del id nativo desde una url pegada a mano.

Formatos verificados en navegador sin sesión el 2026-10-17:
- LinkedIn: /feed/update/urn:li:activity:ID/ abre el post.
- TikTok: /@/video/ID abre el video (redirige a la url completa); /video/ID da 404.
"""

import re
from urllib.parse import parse_qs, urlparse

from radar.contrato.base import PREFIJO_ID, Plataforma

PATRON_ID_NATIVO: dict[Plataforma, re.Pattern[str]] = {
    Plataforma.YOUTUBE: re.compile(r"^[A-Za-z0-9_-]{11}$"),
    Plataforma.TIKTOK: re.compile(r"^\d{15,22}$"),
    Plataforma.LINKEDIN: re.compile(r"^\d{15,22}$"),
}

PLANTILLA_URL: dict[Plataforma, str] = {
    Plataforma.YOUTUBE: "https://www.youtube.com/watch?v={id}",
    Plataforma.TIKTOK: "https://www.tiktok.com/@/video/{id}",
    Plataforma.LINKEDIN: "https://www.linkedin.com/feed/update/urn:li:activity:{id}/",
}

_YOUTUBE_RUTA = re.compile(r"^/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})")
_TIKTOK_RUTA = re.compile(r"/video/(\d{15,22})")
_LINKEDIN_ACTIVIDAD = re.compile(r"activity[:\-](\d{15,22})")


def es_id_nativo_valido(plataforma: Plataforma, id_nativo: str) -> bool:
    return bool(PATRON_ID_NATIVO[plataforma].match(id_nativo))


def url_canonica(plataforma: Plataforma, id_nativo: str) -> str:
    if not es_id_nativo_valido(plataforma, id_nativo):
        raise ValueError(f"id nativo inválido para {plataforma.value}: {id_nativo!r}")
    return PLANTILLA_URL[plataforma].format(id=id_nativo)


def id_desde_url(url: str) -> tuple[Plataforma, str]:
    """Devuelve (plataforma, id nativo) a partir de una url copiada del navegador."""
    partes = urlparse(url.strip())
    host = (partes.hostname or "").removeprefix("www.").removeprefix("m.")

    if host in ("youtube.com", "youtu.be"):
        candidato = _id_youtube(host, partes.path, partes.query)
        plataforma = Plataforma.YOUTUBE
    elif host.endswith("tiktok.com"):
        coincidencia = _TIKTOK_RUTA.search(partes.path)
        candidato = coincidencia.group(1) if coincidencia else None
        plataforma = Plataforma.TIKTOK
    elif host.endswith("linkedin.com"):
        coincidencia = _LINKEDIN_ACTIVIDAD.search(partes.path)
        candidato = coincidencia.group(1) if coincidencia else None
        plataforma = Plataforma.LINKEDIN
    else:
        raise ValueError(f"La url no es de YouTube, TikTok ni LinkedIn: {host or url!r}")

    if not candidato or not es_id_nativo_valido(plataforma, candidato):
        raise ValueError(
            f"No se encontró el id de la publicación en la url de {plataforma.value}. "
            "Si es un link compartido desde la app, ábrelo en el navegador y copia la url completa "
            "(debe tener /video/ en TikTok o activity en LinkedIn)."
        )
    return plataforma, candidato


def id_contrato(plataforma: Plataforma, id_nativo: str) -> str:
    """Id del contrato con prefijo de plataforma, ej. 'yt:dQw4w9WgXcQ'."""
    if not es_id_nativo_valido(plataforma, id_nativo):
        raise ValueError(f"id nativo inválido para {plataforma.value}: {id_nativo!r}")
    return f"{PREFIJO_ID[plataforma]}:{id_nativo}"


def _id_youtube(host: str, ruta: str, consulta: str) -> str | None:
    if host == "youtu.be":
        return ruta.lstrip("/").split("/")[0] or None
    if ruta == "/watch":
        return (parse_qs(consulta).get("v") or [None])[0]
    coincidencia = _YOUTUBE_RUTA.match(ruta)
    return coincidencia.group(1) if coincidencia else None
