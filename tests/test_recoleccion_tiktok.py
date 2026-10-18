import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from radar.contrato import Metrica, Origen, Plataforma, calcular_autor_hash
from radar.recoleccion import tiktok

URL = "https://www.tiktok.com/@usuario_ficticio/video/1234567890123456789"


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail("No se permite red en las pruebas")
    monkeypatch.setattr("socket.socket.connect", prohibido)


@pytest.fixture
def info():
    return json.loads((Path(__file__).parent / "fixtures/tiktok_video.json").read_text(encoding="utf-8"))


def test_mapea_y_anonimiza(info):
    antes = datetime.now(timezone.utc)
    p, m = tiktok.recolectar(URL, sal="sal_ficticia", extractor=lambda _:info)
    assert p.origen == m.origen == Origen.PAGINA_PUBLICA
    assert p.id == m.publicacion_id == "tt:1234567890123456789"
    assert p.capturada_en == m.capturada_en and p.capturada_en >= antes
    assert p.publicada_en == datetime.fromtimestamp(info["timestamp"], timezone.utc)
    assert p.duracion_segundos == 53 and p.formato == "video_corto"
    assert p.hashtags == ("ia", "agentes")
    assert (m.vistas,m.likes,m.comentarios,m.compartidos) == (1200,0,None,2)
    assert p.autor_hash == calcular_autor_hash(Plataforma.TIKTOK,"id_autor_ficticio","sal_ficticia")
    salida = p.model_dump_json() + m.model_dump_json()
    for dato in ("usuario_ficticio", "id_autor_ficticio", "Nombre Ficticio", "mencion_ficticia"):
        assert dato not in salida
    assert "@[usuario]" in p.texto


def test_csv_gana_para_texto_fecha(info):
    fecha = datetime(2026,1,1,tzinfo=timezone.utc)
    p, _ = tiktok.recolectar(URL,sal="sal",extractor=lambda _:info,
        texto="Texto manual @mencion_ficticia #IA",publicada_en=fecha)
    assert p.texto == "Texto manual @[usuario] #IA" and p.publicada_en == fecha


@pytest.mark.parametrize("segundos,formato", [(180,"video_corto"),(181,"video_largo")])
def test_umbral(info,segundos,formato):
    info["duration"] = segundos
    assert tiktok.recolectar(URL,sal="sal",extractor=lambda _:info)[0].formato == formato


def test_sin_metricas_no_inventa_ceros(info):
    for campo in ("view_count","like_count","comment_count","repost_count"):
        info.pop(campo,None)
    assert tiktok.recolectar(URL,sal="sal",extractor=lambda _:info)[1] is None


def test_extractor_falla_sin_exponer_datos():
    def fallar(_): raise RuntimeError("usuario_privado")
    with pytest.raises(ValueError) as exc:
        tiktok.recolectar(URL,sal="sal",extractor=fallar)
    assert "usuario_privado" not in str(exc.value)


def test_ydl_sin_descargar(monkeypatch,info):
    import yt_dlp
    opciones = []
    class YDL:
        def __init__(self,opts): opciones.append(opts)
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def extract_info(self,url,download):
            assert url == URL and download is False
            return info
    monkeypatch.setattr(yt_dlp,"YoutubeDL",YDL)
    tiktok.recolectar(URL,sal="sal")
    assert opciones[0]["skip_download"] and opciones[0]["quiet"]
    assert not opciones[0].get("cookiefile")


def test_origen_admitido_en_contrato(info):
    p,m = tiktok.recolectar(URL,sal="sal",extractor=lambda _:info)
    assert Metrica.model_validate_json(m.model_dump_json()) == m
