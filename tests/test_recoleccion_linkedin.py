from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from radar.contrato import Plataforma, calcular_autor_hash
from radar.recoleccion import linkedin

URL = "https://www.linkedin.com/posts/autorficticio_ia-activity-2234567890123456789-abcd"
CORTA = "https://lnkd.in/p/ficticio"


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    monkeypatch.setattr("socket.socket.connect", lambda *a:pytest.fail("Red prohibida"))


@pytest.fixture
def html():
    return (Path(__file__).parent / "fixtures/linkedin_post.html").read_text(encoding="utf-8")


def test_jsonld_privacidad_y_metricas(html):
    antes = datetime.now(timezone.utc)
    p,m = linkedin.recolectar(URL,sal="sal",obtener=lambda _: (URL,html))
    assert p.id == m.publicacion_id == "li:2234567890123456789"
    assert p.origen == m.origen == "pagina_publica"
    assert p.capturada_en == m.capturada_en and p.capturada_en >= antes
    assert p.publicada_en == datetime(2026,1,2,15,tzinfo=timezone.utc)
    assert (m.vistas,m.likes,m.comentarios,m.compartidos) == (None,12,0,2)
    assert p.hashtags == ("ia",) and p.formato == "post_texto"
    assert p.autor_hash == calcular_autor_hash(Plataforma.LINKEDIN,"autorficticio","sal")
    salida = p.model_dump_json() + m.model_dump_json()
    for dato in ("Nombre Ficticio","autorficticio","mencion_ficticia","<script"):
        assert dato not in salida
    assert "@[usuario]" in p.texto


def test_acortado_y_prioridad_csv(html):
    fecha=datetime(2026,1,1,tzinfo=timezone.utc)
    p,_=linkedin.recolectar(CORTA,sal="sal",obtener=lambda _: (URL,html),
        texto="Texto manual @alguien #IA",publicada_en=fecha)
    assert p.publicada_en == fecha and p.texto == "Texto manual @[usuario] #IA"
    assert p.autor_hash == calcular_autor_hash(Plataforma.LINKEDIN,"https://www.linkedin.com/in/autorficticio","sal")


@pytest.mark.parametrize("destino",["https://evil.test/posts/123", "https://www.linkedin.com/in/alguien", "https://www.linkedin.com.evil.test/posts/123"])
def test_destino_rechazado(destino,html):
    with pytest.raises(ValueError):
        linkedin.recolectar(CORTA,sal="sal",obtener=lambda _: (destino,html))


def test_sin_jsonld_error_seguro():
    with pytest.raises(ValueError) as exc:
        linkedin.recolectar(URL,sal="sal",obtener=lambda _: (URL,"<html>dato_privado</html>"))
    assert "dato_privado" not in str(exc.value)


@pytest.mark.parametrize("codigo",[429,999])
def test_bloqueos_no_se_reintentan(codigo):
    llamadas=[]
    def obtener(url):
        llamadas.append(url)
        raise HTTPError(url,codigo,"contenido_privado",{},None)
    with pytest.raises(linkedin.BloqueoLinkedIn):
        linkedin.recolectar(URL,sal="sal",obtener=obtener)
    assert llamadas == [URL]


@pytest.mark.parametrize("destino,cuerpo",[
    ("https://www.linkedin.com/login",""),
    (URL,'<form action="/uas/login-submit"><input name="session_password"></form>')])
def test_pide_sesion(destino,cuerpo):
    with pytest.raises(linkedin.BloqueoLinkedIn):
        linkedin.recolectar(URL,sal="sal",obtener=lambda _: (destino,cuerpo))


def test_http_sin_cookies_y_timeout(monkeypatch,html):
    class Respuesta:
        headers={}
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def geturl(self): return URL
        def read(self): return html.encode()
    class Opener:
        def open(self,request,timeout):
            assert timeout==20 and isinstance(request,Request)
            assert not request.has_header("Cookie")
            return Respuesta()
    def construir(handler):
        assert isinstance(handler,linkedin.RedireccionesPublicas)
        return Opener()
    monkeypatch.setattr(linkedin,"build_opener",construir)
    assert linkedin.recolectar(CORTA,sal="sal")[0].id == "li:2234567890123456789"


def test_redireccion_valida_antes_de_seguir():
    handler=linkedin.RedireccionesPublicas()
    request=Request(CORTA)
    destino=handler.redirect_request(request,None,302,"Found",{},URL)
    assert destino.full_url==URL
    with pytest.raises(ValueError):
        handler.redirect_request(request,None,302,"Found",{},"https://evil.test/posts/123")


def test_metricas_ausentes(html):
    import json
    vacio='<script type="application/ld+json">'+json.dumps({
        "@type":"SocialMediaPosting","datePublished":"2026-01-01T00:00:00Z",
        "text":"Idea #IA", "author":{"name":"Nombre Ficticio"}})+'</script>'
    assert linkedin.recolectar(URL,sal="sal",obtener=lambda _: (URL,vacio))[1] is None


def test_html_en_texto_jsonld_no_sale(html):
    html=html.replace("Ideas IA", "<p>Ideas &amp; IA</p>")
    p,_=linkedin.recolectar(URL,sal="sal",obtener=lambda _: (URL,html))
    assert "<p>" not in p.texto and "Ideas & IA" in p.texto
