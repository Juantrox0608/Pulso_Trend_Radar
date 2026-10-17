import json
from pathlib import Path

import pytest

from radar.recoleccion import csv_manual, linkedin, tiktok
from test_csv_completar_tiktok import archivo

URL="https://www.linkedin.com/posts/autorficticio_ia-activity-2234567890123456789-abcd"


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("AUTOR_HASH_SAL","sal_ficticia")
    monkeypatch.setattr("socket.socket.connect",lambda *a:pytest.fail("Red prohibida"))


@pytest.fixture
def recolector(monkeypatch):
    html=(Path(__file__).parent / "fixtures/linkedin_post.html").read_text(encoding="utf-8")
    real=linkedin.recolectar; llamadas=[]
    def recolectar(url,**kwargs):
        llamadas.append(url)
        return real(url,obtener=lambda _: (URL,html),**kwargs)
    monkeypatch.setattr(linkedin,"recolectar",recolectar)
    return llamadas


def test_cli_solo_url(tmp_path,recolector,capsys):
    csv_manual.main([str(archivo(tmp_path,[dict(url=URL)])),"--completar-linkedin"])
    salida=json.loads(capsys.readouterr().out)
    assert len(salida["publicaciones"]) == len(salida["metricas"]) == len(recolector) == 1
    assert salida["metricas"][0]["origen"] == "pagina_publica"


def test_apagado_sin_red(tmp_path,monkeypatch):
    monkeypatch.setattr(linkedin,"recolectar",lambda *a,**k:pytest.fail("No debe consultar"))
    with pytest.raises(ValueError):
        csv_manual.leer_con_metricas(archivo(tmp_path,[dict(url=URL)]))


def test_pausa_y_tope(tmp_path,recolector):
    pausas=[]
    ruta=archivo(tmp_path,[dict(url=URL)]*101)
    with pytest.raises(ValueError,match="100"):
        csv_manual.leer_con_metricas(ruta,completar_linkedin=True,pausa=pausas.append)
    assert recolector == []
    ps,ms=csv_manual.leer_con_metricas(archivo(tmp_path,[dict(url=URL)]*2),completar_linkedin=True,pausa=pausas.append)
    assert len(ps)==len(ms)==2 and pausas==[3]


def test_bloqueo_corta_todo_incluso_tiktok(tmp_path,monkeypatch):
    llamadas=[]
    def bloquear(*a,**k):
        llamadas.append(1)
        raise linkedin.BloqueoLinkedIn("LinkedIn: bloqueo público")
    monkeypatch.setattr(linkedin,"recolectar",bloquear)
    monkeypatch.setattr(tiktok,"recolectar",lambda *a,**k:pytest.fail("Corrida debe cortarse"))
    filas=[dict(url=URL),dict(url=URL),dict(url="https://www.tiktok.com/@ficticio/video/1234567890123456789")]
    with pytest.raises(ValueError) as exc:
        csv_manual.leer_con_metricas(archivo(tmp_path,filas),completar_linkedin=True,completar_tiktok=True,pausa=lambda _:None)
    assert llamadas==[1]
    for linea in (2,3,4):
        assert str(linea) in str(exc.value)


def test_repara_texto_csv_conservando_acentos(tmp_path):
    filas=[dict(url=URL,autor="autorficticio",fecha_publicacion="2026-01-01",formato="post_texto",texto="IA podrÃ­a MEJORAR la educación")]
    p=csv_manual.leer_con_metricas(archivo(tmp_path,filas))[0][0]
    assert p.texto=="IA podría MEJORAR la educación"
    # Una celda completamente mojibake y otra correcta mantienen mayúsculas y tildes.
    filas[0]["texto"]="IA podrÃ­a MEJORAR la educaciÃ³n"
    p=csv_manual.leer_con_metricas(archivo(tmp_path,filas))[0][0]
    assert p.texto=="IA podría MEJORAR la educación"


def test_999_real_del_transporte_corta_corrida(tmp_path,monkeypatch):
    from urllib.error import HTTPError
    llamadas=[]
    def obtener(url):
        llamadas.append(url)
        raise HTTPError(url,999,"dato_privado",{},None)
    monkeypatch.setattr(linkedin,"_obtener",obtener)
    with pytest.raises(ValueError) as exc:
        csv_manual.leer_con_metricas(archivo(tmp_path,[dict(url=URL)]*3),completar_linkedin=True,pausa=lambda _:None)
    assert llamadas == [URL]
    assert "999" in str(exc.value) and "2, 3, 4" in str(exc.value)
    assert "dato_privado" not in str(exc.value)


def test_csv_gana_y_metricas_viejas_se_ignoran(tmp_path,recolector):
    filas=[dict(url=URL,texto="Texto manual #IA",fecha_publicacion="2026-01-01",
        reacciones="dato viejo no numérico",fecha_captura="")]
    ps,ms=csv_manual.leer_con_metricas(archivo(tmp_path,filas),completar_linkedin=True)
    assert ps[0].texto=="Texto manual #IA" and ps[0].publicada_en.day==1
    assert ms[0].likes==12 and ms[0].capturada_en==ps[0].capturada_en
