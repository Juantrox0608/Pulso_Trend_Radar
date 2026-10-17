"""Respuestas sintéticas: ninguna prueba usa credenciales reales ni red."""
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
from radar.contrato import Plataforma, Publicacion, calcular_autor_hash
from radar.recoleccion import youtube

DESDE = datetime(2026, 1, 1, tzinfo=timezone.utc)

@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "clave_ficticia")
    monkeypatch.setenv("AUTOR_HASH_SAL", "sal_ficticia")
    def prohibido(*args, **kwargs):
        pytest.fail("Las pruebas no pueden usar la red")
    monkeypatch.setattr("socket.socket.connect", prohibido)
    monkeypatch.setattr(youtube, "urlopen", prohibido)

@pytest.fixture
def api():
    carpeta = Path(__file__).parent / "fixtures"
    respuestas = {ruta: json.loads((carpeta / f"youtube_{ruta}.json").read_text(encoding="utf-8")) for ruta in ("search", "videos")}
    llamadas = []
    def pedir(ruta, parametros):
        llamadas.append((ruta, parametros))
        return respuestas[ruta]
    return respuestas, llamadas, pedir

def recolectar(api, **kwargs):
    return youtube.buscar_publicaciones("agentes de IA", "mx", "es", DESDE, peticion=api[2], **kwargs)

def test_mapeo_y_dos_peticiones(api):
    antes = datetime.now(timezone.utc)
    publicaciones = recolectar(api)
    assert len(publicaciones) == 2
    corta, larga = publicaciones
    assert isinstance(corta, Publicacion)
    assert corta.id == "yt:vid_test01A"
    assert corta.url == "https://www.youtube.com/watch?v=vid_test01A"
    assert corta.titulo == "Agentes de IA"
    assert corta.texto == "Descripción de ejemplo"
    assert corta.hashtags == ("ia", "agentes")
    assert (corta.formato, larga.formato) == ("video_corto", "video_largo")
    assert (corta.duracion_segundos, larga.duracion_segundos) == (180, 181)
    assert corta.publicada_en == datetime(2026, 1, 2, 15, tzinfo=timezone.utc)
    assert antes <= corta.capturada_en <= datetime.now(timezone.utc)
    assert corta.idioma == "es" and corta.pais == "MX"
    assert corta.origen == "api_oficial" and corta.tipo_autor == "desconocido"
    assert corta.autor_hash == calcular_autor_hash(Plataforma.YOUTUBE, "canal_ficticio", "sal_ficticia")
    serializado = json.dumps([p.model_dump(mode="json") for p in publicaciones])
    for excluido in ("canal_ficticio", "CANAL_SINTETICO_NO_DEVOLVER", "channelTitle", "clave_ficticia", "sal_ficticia"):
        assert excluido not in serializado
    assert [ruta for ruta, _ in api[1]] == ["search", "videos"]
    search, videos = [parametros for _, parametros in api[1]]
    assert search["part"] == "snippet" and search["type"] == "video"
    assert search["q"] == "agentes de IA"
    assert search["regionCode"] == "MX" and search["relevanceLanguage"] == "es"
    assert search["publishedAfter"] == "2026-01-01T00:00:00Z"
    assert search["maxResults"] == 50
    assert videos["part"] == "snippet,contentDetails,statistics"
    assert videos["id"] == "vid_test01A,vid_test02B"

@pytest.mark.parametrize("duracion,segundos", [("PT0S",0), ("PT59S",59), ("PT1H2M3S",3723), ("P1DT2H",93600)])
def test_duracion(api, duracion, segundos):
    api[0]["videos"]["items"][0]["contentDetails"]["duration"] = duracion
    assert recolectar(api)[0].duracion_segundos == segundos

@pytest.mark.parametrize("duracion", ["", "PT", "P", "no-es-duracion"])
def test_duracion_invalida(api, duracion):
    api[0]["videos"]["items"][0]["contentDetails"]["duration"] = duracion
    with pytest.raises(ValueError):
        recolectar(api)

def test_texto_largo_e_idioma_opcional(api):
    snippet = api[0]["videos"]["items"][0]["snippet"]
    snippet["description"] = "x" * 5100
    del snippet["defaultAudioLanguage"]
    snippet["defaultLanguage"] = "pt-BR"
    assert len(recolectar(api)[0].texto) == 5000
    assert recolectar(api)[0].idioma == "pt"
    del snippet["defaultLanguage"]
    del snippet["tags"]
    assert recolectar(api)[0].idioma is None
    assert recolectar(api)[0].hashtags == ()

def test_quita_etiquetas_con_el_nombre_del_canal(api):
    snippet = api[0]["videos"]["items"][0]["snippet"]
    snippet["channelTitle"] = "Canal Ficticio"
    snippet["tags"] = ["canal ficticio", "#CanalFicticio", "IA"]
    publicacion = recolectar(api)[0]
    assert publicacion.hashtags == ("ia",)
    assert "channelTitle" in api[1][1][1]["fields"]
    assert "ficticio" not in publicacion.model_dump_json().lower()

@pytest.mark.parametrize("estado", ["live", "upcoming"])
def test_salta_transmisiones_en_vivo_y_programadas(api, estado):
    api[0]["videos"]["items"][0]["snippet"]["liveBroadcastContent"] = estado
    api[0]["videos"]["items"][1]["snippet"]["liveBroadcastContent"] = "none"
    publicaciones = recolectar(api)
    assert [p.id for p in publicaciones] == ["yt:vid_test02B"]
    assert "liveBroadcastContent" in api[1][1][1]["fields"]

def test_sin_resultados_no_pide_videos(api):
    api[0]["search"]["items"] = []
    assert recolectar(api) == []
    assert len(api[1]) == 1

def test_video_eliminado_y_ids_duplicados(api):
    api[0]["search"]["items"].append(api[0]["search"]["items"][0])
    api[0]["videos"]["items"].pop()
    assert len(recolectar(api)) == 1
    assert api[1][1][1]["id"] == "vid_test01A,vid_test02B"

@pytest.mark.parametrize("variable", ["YOUTUBE_API_KEY", "AUTOR_HASH_SAL"])
def test_falta_variable(api, monkeypatch, variable):
    monkeypatch.delenv(variable)
    with pytest.raises(ValueError, match=variable):
        recolectar(api)
    assert api[1] == []

@pytest.mark.parametrize("cambio", [{"consulta":" "}, {"pais":"MEX"}, {"idioma":"es-419"}, {"desde":datetime(2026,1,1)}, {"max_resultados":51}, {"max_resultados":0}])
def test_entrada_invalida(api, cambio):
    args = dict(consulta="IA", pais="MX", idioma="es", desde=DESDE, peticion=api[2])
    args.update(cambio)
    with pytest.raises(ValueError):
        youtube.buscar_publicaciones(**args)
    assert api[1] == []

@pytest.mark.parametrize("error", [HTTPError("https://ejemplo/?key=clave_ficticia",403,"clave_ficticia",{},None), URLError("clave_ficticia"), TimeoutError("clave_ficticia")])
def test_error_transporte_sin_filtrar_clave(api, monkeypatch, error):
    def fallar(*args, **kwargs):
        raise error
    monkeypatch.setattr(youtube, "urlopen", fallar)
    with pytest.raises(RuntimeError) as exc:
        youtube.buscar_publicaciones("IA", "MX", "es", DESDE)
    assert "clave_ficticia" not in str(exc.value)
    assert exc.value.__suppress_context__

def test_transporte_json_y_timeout(monkeypatch):
    llamadas = []
    def abrir(url, timeout):
        llamadas.append((url, timeout))
        return BytesIO(b'{"items": []}')
    monkeypatch.setattr(youtube, "urlopen", abrir)
    assert youtube.buscar_publicaciones("IA & datos", "MX", "es", DESDE) == []
    assert "q=IA+%26+datos" in llamadas[0][0]
    assert 0 < llamadas[0][1] <= 60

def test_error_api_sin_copiar_respuesta(api):
    api[0]["search"] = {"error": {"message": "clave_ficticia"}}
    with pytest.raises(RuntimeError) as exc:
        recolectar(api)
    assert "clave_ficticia" not in str(exc.value)

def test_cli_json(api, monkeypatch, capsys):
    real = youtube.buscar_con_metricas
    def buscar(*args, **kwargs):
        assert args[:3] == ("agentes de IA", "MX", "es")
        assert 6.99 < (datetime.now(timezone.utc) - args[3]).total_seconds()/86400 < 7.01
        return real(*args, peticion=api[2], **kwargs)
    monkeypatch.setattr(youtube, "buscar_con_metricas", buscar)
    youtube.main(["agentes de IA", "--pais", "MX", "--dias", "7"])
    datos = json.loads(capsys.readouterr().out)
    assert len(datos["publicaciones"]) == 2 and datos["publicaciones"][0]["url"]
    assert len(datos["metricas"]) == 2


def test_metricas_un_lote_y_ocultas(api):
    publicaciones, metricas = youtube.buscar_con_metricas("IA", "MX", "es", DESDE, peticion=api[2])
    assert len(publicaciones) == len(metricas) == 2
    assert metricas[0].vistas == 1200 and metricas[0].likes == 0
    assert metricas[0].comentarios == 5 and metricas[0].compartidos is None
    assert metricas[1].likes is None and metricas[1].comentarios is None
    for p, m in zip(publicaciones, metricas):
        assert m.publicacion_id == p.id and m.capturada_en == p.capturada_en and m.origen == p.origen
    assert [ruta for ruta, _ in api[1]].count("videos") == 1
    assert "statistics(viewCount,likeCount,commentCount)" in api[1][1][1]["fields"]


def test_sin_estadisticas_no_crea_metrica(api):
    for v in api[0]["videos"]["items"]:
        v.pop("statistics", None)
    publicaciones, metricas = youtube.buscar_con_metricas("IA", "MX", "es", DESDE, peticion=api[2])
    assert len(publicaciones) == 2 and metricas == []


def test_sin_resultados_con_metricas(api):
    api[0]["search"]["items"] = []
    assert youtube.buscar_con_metricas("IA", "MX", "es", DESDE, peticion=api[2]) == ([], [])


@pytest.mark.parametrize("valor", ["-1", "1.5", True, "dato_privado"])
def test_estadistica_invalida_no_filtra_valor(api, valor):
    api[0]["videos"]["items"][0]["statistics"]["likeCount"] = valor
    with pytest.raises(ValueError) as exc:
        youtube.buscar_con_metricas("IA", "MX", "es", DESDE, peticion=api[2])
    assert "dato_privado" not in str(exc.value)


def test_transmision_no_deja_metrica_huerfana(api):
    api[0]["videos"]["items"][0]["snippet"]["liveBroadcastContent"] = "live"
    publicaciones, metricas = youtube.buscar_con_metricas("IA", "MX", "es", DESDE, peticion=api[2])
    assert [p.id for p in publicaciones] == [m.publicacion_id for m in metricas] == ["yt:vid_test02B"]

@pytest.mark.parametrize("args", [["IA", "--dias", "0"], ["IA", "--dias", "-1"]])
def test_cli_dias_invalidos(args):
    with pytest.raises(SystemExit) as exc:
        youtube.main(args)
    assert exc.value.code == 2

def test_cli_error_claro(monkeypatch, capsys):
    monkeypatch.delenv("YOUTUBE_API_KEY")
    with pytest.raises(SystemExit) as exc:
        youtube.main(["IA"])
    assert exc.value.code != 0
    salida = capsys.readouterr()
    assert not salida.out and "YOUTUBE_API_KEY" in salida.err

def test_menciones_y_nombre_en_titulo_y_descripcion(api):
    snippet = api[0]['videos']['items'][0]['snippet']
    snippet['title'] = 'CANAL_SINTETICO_NO_DEVOLVER con @mencion_ficticia'
    snippet['description'] = 'CANAL_SINTETICO_NO_DEVOLVER presenta @mencion_ficticia #IA'
    p = recolectar(api)[0]
    assert p.titulo == '[autor] con @[usuario]'
    assert p.texto == '[autor] presenta @[usuario] #IA'
