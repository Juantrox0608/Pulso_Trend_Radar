"""Metadatos públicos de TikTok mediante yt-dlp, sin descargar videos ni cookies."""
from datetime import datetime, timezone
from urllib.parse import urlsplit

import yt_dlp

from radar.contrato import Metrica, Plataforma, Publicacion, calcular_autor_hash, id_contrato, id_desde_url
from radar.recoleccion import texto_publico, titulo_publico


class _SinLog:
    def debug(self, *args): pass
    def warning(self, *args): pass
    def error(self, *args): pass


def _extraer(url):
    # No imprimir errores del proveedor: pueden contener el usuario o la URL original.
    with yt_dlp.YoutubeDL({"skip_download": True, "quiet": True, "no_warnings": True,
                    "logger": _SinLog(), "socket_timeout": 20, "retries": 0,
                    "extractor_retries": 0, "noplaylist": True}) as ydl:
        return ydl.extract_info(url, download=False)


def recolectar(url: str, *, sal: str, extractor=None, texto=None, publicada_en=None,
               tipo_autor="desconocido", idioma=None, pais=None):
    """Devuelve solo el contrato anonimizado; el extractor inyectable permite pruebas sin red."""
    try:
        partes = urlsplit(url)
        host = partes.hostname or ""
        if (partes.scheme != "https" or partes.username or partes.password
                or partes.port not in (None, 443)
                or not (host == "tiktok.com" or host.endswith(".tiktok.com"))):
            raise ValueError()
        plataforma, nativo = id_desde_url(url)
        info = (extractor or _extraer)(url)
        return convertir_entrada(info, sal=sal, texto=texto, publicada_en=publicada_en,
                                tipo_autor=tipo_autor, idioma=idioma, pais=pais, nativo=nativo)
    except Exception:
        raise ValueError("TikTok: no se pudieron obtener metadatos públicos válidos") from None


def convertir_entrada(info, *, sal, ahora=None, texto=None, publicada_en=None,
                      tipo_autor="desconocido", idioma=None, pais=None, nativo=None):
    """Convierte metadatos de video o de lista plana al mismo contrato anonimizado."""
    plataforma = Plataforma.TIKTOK
    nativo = nativo or str(info["id"])
    autores = tuple(str(info.get(k) or "") for k in ("uploader_id", "uploader", "channel", "channel_id"))
    autor = next((a for a in autores if a), "")
    if not autor or str(info.get("id")) != nativo:
        raise ValueError()
    contenido, hashtags = texto_publico(texto or info.get("description") or "", *autores)
    duracion = info.get("duration")
    duracion = int(duracion) if duracion is not None else None
    ahora = ahora or datetime.now(timezone.utc)
    p = Publicacion(id=id_contrato(plataforma, nativo), plataforma=plataforma,
        titulo=titulo_publico(info.get('title'), contenido, *autores),
        texto=contenido, hashtags=hashtags, duracion_segundos=duracion,
        # shortcut: la duración aproxima el formato, no identifica excepciones editoriales.
        formato="video_corto" if duracion is None or duracion <= 180 else "video_largo",
        publicada_en=publicada_en or datetime.fromtimestamp(info["timestamp"], timezone.utc),
        capturada_en=ahora, origen="pagina_publica", tipo_autor=tipo_autor,
        idioma=idioma, pais=pais, autor_hash=calcular_autor_hash(plataforma, autor, sal))
    conteos = dict(zip(("vistas", "likes", "comentarios", "compartidos"),
                      (info.get(k) for k in ("view_count", "like_count", "comment_count", "repost_count"))))
    m = Metrica(publicacion_id=p.id, capturada_en=ahora, origen=p.origen, **conteos) if any(
        v is not None for v in conteos.values()) else None
    return p, m
