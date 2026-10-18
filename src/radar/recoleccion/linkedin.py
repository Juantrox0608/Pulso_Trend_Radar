"""Lectura de publicaciones públicas, sin sesión, cookies ni almacenamiento de HTML."""
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from radar.contrato import Metrica, Publicacion, calcular_autor_hash, id_contrato, id_desde_url
from radar.recoleccion import texto_publico, titulo_publico, segundos_iso8601


class BloqueoLinkedIn(ValueError):
    """Exige detener la corrida completa; no debe reintentarse."""


def _validar_url(url, *, final=False):
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if (p.scheme != "https" or p.username or p.password or p.port not in (None, 443)
            or not (host == "lnkd.in" or host == "linkedin.com" or host.endswith(".linkedin.com"))):
        raise ValueError("LinkedIn: destino público no permitido")
    if host != "lnkd.in" and re.match(r"/(?:login|uas|authwall|checkpoint)(?:/|$)", p.path):
        raise BloqueoLinkedIn("LinkedIn solicita iniciar sesión; corrida detenida")
    if (final or host != "lnkd.in") and (host == "lnkd.in" or not p.path.startswith(("/posts/", "/feed/update/"))):
        raise ValueError("LinkedIn: el destino no es una publicación pública")


class RedireccionesPublicas(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validar_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _obtener(url):
    request = Request(url, headers={"User-Agent": "Radar/0.1 (public metadata)", "Accept": "text/html"})
    # El opener estándar no incluye gestión de cookies; cada publicación usa uno nuevo.
    with build_opener(RedireccionesPublicas()).open(request, timeout=20) as respuesta:
        destino = respuesta.geturl()
        _validar_url(destino, final=True)
        return destino, respuesta.read().decode("utf-8")


class _Pagina(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bloques = []
        self.partes = None

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if tag == "script" and atributos.get("type", "").lower() == "application/ld+json":
            self.partes = []

    def handle_data(self, data):
        if self.partes is not None:
            self.partes.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.partes is not None:
            self.bloques.append("".join(self.partes))
            self.partes = None


class _Texto(HTMLParser):
    """El texto de JSON-LD puede incluir etiquetas; no pasan al contrato."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes = []

    def handle_data(self, data):
        self.partes.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "div"):
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in ("p", "div"):
            self.partes.append("\n")


def _buscar_post(valor):
    if isinstance(valor, dict):
        tipos = valor.get("@type", [])
        tipos = [tipos] if isinstance(tipos, str) else tipos
        if any(str(t).rsplit("/", 1)[-1] in ("SocialMediaPosting", "VideoObject") for t in tipos):
            return valor
        for hijo in valor.values():
            encontrado = _buscar_post(hijo)
            if encontrado is not None:
                return encontrado
    elif isinstance(valor, list):
        for hijo in valor:
            encontrado = _buscar_post(hijo)
            if encontrado is not None:
                return encontrado
    return None


def recolectar(url: str, *, sal: str, obtener=None, texto=None, publicada_en=None,
               tipo_autor="desconocido", idioma=None, pais=None, formato=None):
    """El HTML solo vive en memoria; la salida contiene exclusivamente el contrato."""
    try:
        _validar_url(url)
        destino, html = (obtener or _obtener)(url)
        _validar_url(destino, final=True)
        pagina = _Pagina()
        pagina.feed(html)
        post = None
        for bloque in pagina.bloques:
            try:
                post = _buscar_post(json.loads(bloque))
            except json.JSONDecodeError:
                continue
            if post is not None:
                break
        if post is None:
            raise ValueError()
        identificable = destino
        destacado = parse_qs(urlsplit(destino).query).get("highlightedUpdateUrn", [""])[0]
        if re.fullmatch(r"urn:li:activity:\d{15,22}", destacado):
            identificable = "https://www.linkedin.com/feed/update/" + destacado + "/"
        plataforma, nativo = id_desde_url(identificable)
        autor = post.get("author") or post.get("creator") or {}
        if isinstance(autor, list):
            autor = autor[0] if autor else {}
        if isinstance(autor, str):
            autor = {"name": autor}
        # Si el enlace original trae usuario, mantiene la misma identidad que el CSV manual.
        encontrado = re.search(r"/posts/([^/_]+)_", unquote(urlsplit(url).path))
        del_enlace = encontrado.group(1) if encontrado else ""
        autor_url = autor.get("url") or autor.get("@id") or ""
        usuario = urlsplit(autor_url).path.rstrip("/").rsplit("/", 1)[-1] if autor_url else ""
        identidad = del_enlace or autor_url or autor.get("name")
        if not identidad:
            raise ValueError()
        limpio = _Texto()
        limpio.feed(texto or post.get("articleBody") or post.get("text") or post.get("description") or "")
        contenido, hashtags = texto_publico("".join(limpio.partes).strip(),
            del_enlace, usuario, autor.get("name", ""), autor_url)
        encabezado = _Texto()
        encabezado.feed(post.get('headline') or '')
        titulo = titulo_publico(''.join(encabezado.partes), contenido,
            del_enlace, usuario, autor.get('name', ''), autor_url)
        fecha = publicada_en or datetime.fromisoformat(post["datePublished"])
        if fecha.utcoffset() is None:
            raise ValueError()
        ahora = datetime.now(timezone.utc)
        tipos = post.get("@type", [])
        tipos = [tipos] if isinstance(tipos, str) else tipos
        video = any(t.rsplit("/", 1)[-1] == "VideoObject" for t in tipos)
        duracion = None
        if video:
            try:
                duracion = segundos_iso8601(post.get("duration") or "")
            except (TypeError, ValueError):
                pass
        if formato:
            manual = re.fullmatch(r"video (\d+)s", formato)
            if manual:
                duracion = int(manual.group(1))
                formato = "video_corto" if duracion <= 180 else "video_largo"
        else:
            # shortcut: <=180 s aproxima video corto; sin duración se mantiene corto, revisar con metadata mejor.
            formato = ("video_corto" if duracion is None or duracion <= 180 else "video_largo") if video else "post_texto"
        p = Publicacion(id=id_contrato(plataforma, nativo), plataforma=plataforma,
            titulo=titulo, texto=contenido, hashtags=hashtags, formato=formato, duracion_segundos=duracion, publicada_en=fecha,
            capturada_en=ahora, origen="pagina_publica", tipo_autor=tipo_autor,
            idioma=idioma, pais=pais, autor_hash=calcular_autor_hash(plataforma, identidad, sal))
        conteos = {"likes": None, "comentarios": post.get("commentCount"), "compartidos": None}
        estadisticas = post.get("interactionStatistic") or []
        if isinstance(estadisticas, dict):
            estadisticas = [estadisticas]
        for estadistica in estadisticas:
            accion = estadistica.get("interactionType", "")
            if isinstance(accion, dict):
                accion = accion.get("@type", "")
            campo = {"LikeAction": "likes", "CommentAction": "comentarios", "ShareAction": "compartidos"}.get(accion.rsplit("/",1)[-1])
            if campo:
                valor = estadistica.get("userInteractionCount")
                conteos[campo] = valor
        conteos = {k: int(v) if isinstance(v, str) and v.isdigit() else v for k,v in conteos.items()}
        m = Metrica(publicacion_id=p.id, capturada_en=ahora, origen=p.origen, **conteos) if any(
            v is not None for v in conteos.values()) else None
        return p, m
    except BloqueoLinkedIn:
        raise
    except HTTPError as error:
        if error.code in (429, 999):
            raise BloqueoLinkedIn(f"LinkedIn respondió {error.code}; corrida detenida sin reintentos") from None
        raise ValueError("LinkedIn: no se pudo consultar la publicación pública") from None
    except Exception:
        raise ValueError("LinkedIn: no se encontraron metadatos públicos válidos") from None
