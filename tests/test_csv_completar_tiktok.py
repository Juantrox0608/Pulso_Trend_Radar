import csv
import json
from pathlib import Path

import pytest

from radar.recoleccion import csv_manual, tiktok


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("AUTOR_HASH_SAL","sal_ficticia")
    monkeypatch.setattr("socket.socket.connect", lambda *a:pytest.fail("No se permite red"))


def archivo(tmp_path,filas):
    ruta = tmp_path / "ejemplo.csv"
    with ruta.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(filas[0])); writer.writeheader(); writer.writerows(filas)
    return ruta


@pytest.fixture
def recolector(monkeypatch):
    info=json.loads((Path(__file__).parent / "fixtures/tiktok_video.json").read_text(encoding="utf-8"))
    real=tiktok.recolectar; llamadas=[]
    def recolectar(url,**kwargs):
        llamadas.append(url)
        return real(url,extractor=lambda _:{**info, "id": url.rsplit("/",1)[-1]},**kwargs)
    monkeypatch.setattr(tiktok,"recolectar",recolectar)
    return llamadas


def test_solo_url_y_cli(tmp_path,recolector,capsys):
    ruta=archivo(tmp_path,[dict(url="https://www.tiktok.com/@ficticio/video/1234567890123456789")])
    csv_manual.main([str(ruta),"--completar-tiktok"])
    datos=json.loads(capsys.readouterr().out)
    assert len(datos["publicaciones"]) == len(datos["metricas"]) == len(recolector) == 1
    assert datos["metricas"][0]["origen"] == "pagina_publica"


def test_apagado_no_llama_extractor(tmp_path,monkeypatch):
    monkeypatch.setattr(tiktok,"recolectar",lambda *a,**kw:pytest.fail("No debe extraer"))
    with pytest.raises(ValueError):
        csv_manual.leer_con_metricas(archivo(tmp_path,[dict(url="https://www.tiktok.com/@ficticio/video/1234567890123456789")]))


def test_pausa_y_tope_antes_de_red(tmp_path,recolector):
    filas=[dict(url=f"https://www.tiktok.com/@ficticio/video/{1234567890123456789+i}") for i in range(101)]
    pausas=[]
    with pytest.raises(ValueError,match="100"):
        csv_manual.leer_con_metricas(archivo(tmp_path,filas),completar_tiktok=True,pausa=pausas.append)
    assert recolector == []
    ps,ms=csv_manual.leer_con_metricas(archivo(tmp_path,filas[:2]),completar_tiktok=True,pausa=pausas.append)
    assert len(ps)==len(ms)==2 and pausas == [1.5]


def test_fallo_listado_por_fila(tmp_path,monkeypatch):
    def fallar(*a,**kw): raise ValueError("No se pudo consultar TikTok")
    monkeypatch.setattr(tiktok,"recolectar",fallar)
    filas=[dict(url=f"https://www.tiktok.com/@ficticio/video/{1234567890123456789+i}") for i in range(2)]
    with pytest.raises(ValueError) as exc:
        csv_manual.leer_con_metricas(archivo(tmp_path,filas),completar_tiktok=True,pausa=lambda _:None)
    assert "Línea 2" in str(exc.value) and "Línea 3" in str(exc.value)
