"""CSV sintéticos; ninguna prueba necesita red, secretos ni datos de Juan."""
import csv
import json
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pytest

from radar.contrato import Plataforma, calcular_autor_hash
from radar.recoleccion import csv_manual

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("AUTOR_HASH_SAL", "sal_sintetica")
    def sin_red(*args, **kwargs):
        pytest.fail("Las pruebas no pueden usar la red")
    monkeypatch.setattr("socket.socket.connect", sin_red)


def archivo(tmp_path, filas, *, separador=",", encoding="utf-8-sig"):
    salida = StringIO(newline="")
    writer = csv.DictWriter(salida, fieldnames=list(filas[0]), delimiter=separador)
    writer.writeheader()
    writer.writerows(filas)
    ruta = tmp_path / "ejemplo.csv"
    ruta.write_bytes(salida.getvalue().encode(encoding))
    return ruta


@pytest.fixture
def fila():
    return dict(url="https://www.tiktok.com/@usuario_ficticio/video/1234567890123456789",
                fecha_publicacion="2026-01-01", texto="Ejemplo ficticio, con coma",
                formato="video_corto", autor="", hashtags="", tipo_autor="", pais="", idioma="",
                fecha_captura="2026-01-05")


@pytest.mark.parametrize("nombre", ["manual_comas.csv", "manual_excel.csv"])
def test_fixtures_mapeo_y_privacidad(nombre):
    antes = datetime.now(timezone.utc)
    publicaciones = csv_manual.leer_publicaciones(FIXTURES / nombre)
    assert len(publicaciones) == 2
    tt, li = publicaciones
    assert tt.id == "tt:1234567890123456789"
    assert tt.autor_hash == calcular_autor_hash(Plataforma.TIKTOK, "usuario_ficticio", "sal_sintetica")
    assert tt.publicada_en == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert tt.capturada_en == datetime(2026, 1, 5, tzinfo=timezone.utc)
    assert tt.origen == "csv_manual" and tt.tipo_autor == "desconocido"
    assert tt.hashtags == ()
    assert li.autor_hash == calcular_autor_hash(Plataforma.LINKEDIN, "autor-ficticio", "sal_sintetica")
    assert li.hashtags == ("ia", "agentes")
    assert li.pais == "MX" and li.idioma == "es"
    assert li.publicada_en == datetime(2026, 1, 2, 15, tzinfo=timezone.utc)
    serializado = json.dumps([p.model_dump(mode="json") for p in publicaciones])
    for dato in ("usuario_ficticio", "autor-ficticio", "/posts/", "sal_sintetica", "reacciones", "vistas"):
        assert dato not in serializado


@pytest.mark.parametrize("autor,hashtags", [
    ("Ana Ficticia", "#AnaFicticia #ia"),
    ("", "#usuario_ficticio #IA"),
    ("Marca Ficticia", "#marca-ficticia, #ia"),
])
def test_quita_hashtags_con_el_nombre_del_autor(tmp_path, fila, autor, hashtags):
    fila.update(autor=autor, hashtags=hashtags)
    p = csv_manual.leer_publicaciones(archivo(tmp_path, [fila]))[0]
    assert p.hashtags == ("ia",)


@pytest.mark.parametrize("segundos,formato", [(53,"video_corto"), (180,"video_corto"), (181,"video_largo")])
def test_excel_normaliza(tmp_path, fila, segundos, formato):
    fila.update(fecha_publicacion="2/01/2026", formato=f"video {segundos}s",
                tipo_autor="creador (educación)", idioma="español", pais="México")
    p = csv_manual.leer_publicaciones(archivo(tmp_path, [fila], separador=";", encoding="cp1252"))[0]
    assert (p.formato, p.duracion_segundos) == (formato, segundos)
    assert (p.tipo_autor, p.idioma, p.pais) == ("creador", "es", "MX")


@pytest.mark.parametrize("pais,codigo", [("Colombia","CO"), ("Argentina","AR"), ("Perú","PE"), ("Chile","CL"), ("Brasil","BR"), ("España","ES"), ("Estados Unidos","US"), ("Us","US"), ("N/D",None), ("MÃ©xico","MX"), ("PerÃº","PE"), ("EspaÃ±a","ES")])
def test_paises(tmp_path, fila, pais, codigo):
    fila["pais"] = pais
    assert csv_manual.leer_publicaciones(archivo(tmp_path, [fila]))[0].pais == codigo


@pytest.mark.parametrize("idioma,codigo", [("espanol","es"), ("inglés","en"), ("ingles","en"), ("portugués","pt"), ("es-419","es")])
def test_idiomas(tmp_path, fila, idioma, codigo):
    fila["idioma"] = idioma
    assert csv_manual.leer_publicaciones(archivo(tmp_path, [fila]))[0].idioma == codigo


@pytest.mark.parametrize("campo,valor", [("pais","desconocido"), ("idioma","inventado"), ("formato","video"), ("fecha_publicacion","2026-01-01T12:00:00"), ("fecha_publicacion","31/02/2026"), ("texto",""), ("texto","x"*5001), ("tipo_autor","otro"), ("url","https://evil-tiktok.com/@usuario_ficticio/video/1234567890123456789"), ("url","https://www.youtube.com/watch?v=vid_test01A")])
def test_fila_invalida(tmp_path, fila, campo, valor):
    fila[campo] = valor
    with pytest.raises(ValueError, match="Línea 2"):
        csv_manual.leer_publicaciones(archivo(tmp_path, [fila]))


def test_errores_agregados_sin_datos(tmp_path, fila):
    filas = [fila, {**fila, "url":"https://sitio-invalido.test/dato_privado"}, {**fila, "formato":"formato_privado"}]
    with pytest.raises(ValueError) as exc:
        csv_manual.leer_publicaciones(archivo(tmp_path, filas))
    assert "Línea 3" in str(exc.value) and "Línea 4" in str(exc.value)
    assert "dato_privado" not in str(exc.value) and "formato_privado" not in str(exc.value)


def test_encabezados_reordenados_y_filas_vacias(tmp_path, fila):
    fila = dict(reversed(list(fila.items())))
    vacia = dict.fromkeys(fila, " ")
    assert len(csv_manual.leer_publicaciones(archivo(tmp_path, [vacia, fila, vacia]))) == 1


def test_puerto_invalido_no_expone_valor(tmp_path, fila):
    fila["url"] = "https://www.tiktok.com:dato_privado/@usuario_ficticio/video/1234567890123456789"
    with pytest.raises(ValueError) as exc:
        csv_manual.leer_publicaciones(archivo(tmp_path, [fila]))
    assert "dato_privado" not in str(exc.value)


def test_csv_malformado_error_seguro(tmp_path):
    ruta = tmp_path / "malformado.csv"
    ruta.write_text('url,fecha_publicacion,texto,formato\n"sin_cierre', encoding="utf-8")
    with pytest.raises(ValueError, match="estructura CSV"):
        csv_manual.leer_publicaciones(ruta)


def test_falta_columna(tmp_path, fila):
    del fila["texto"]
    with pytest.raises(ValueError, match="texto"):
        csv_manual.leer_publicaciones(archivo(tmp_path, [fila]))


def test_sin_autor_extraible(tmp_path, fila):
    fila["url"] = "https://www.linkedin.com/feed/update/urn:li:activity:1234567890123456789/"
    with pytest.raises(ValueError, match="autor"):
        csv_manual.leer_publicaciones(archivo(tmp_path, [fila]))


def test_falta_sal(tmp_path, fila, monkeypatch):
    monkeypatch.delenv("AUTOR_HASH_SAL")
    with pytest.raises(ValueError, match="AUTOR_HASH_SAL"):
        csv_manual.leer_publicaciones(archivo(tmp_path, [fila]))


def test_link_abreviado_local(tmp_path, fila):
    fila.update(url="https://lnkd.in/e/ABcd1234", autor="autor-ficticio")
    p = csv_manual.leer_publicaciones(archivo(tmp_path, [fila]))[0]
    assert p.id == "li:lnkd-e-ABcd1234"
    assert p.url == "https://lnkd.in/e/ABcd1234"
    assert p.autor_hash == calcular_autor_hash(Plataforma.LINKEDIN, "autor-ficticio", "sal_sintetica")


def test_dos_urls_pegadas_motivo_util(tmp_path, fila):
    fila.update(url="https://lnkd.in/e/ABcd1234https://lnkd.in/e/ZYxw9876", autor="autor-ficticio")
    with pytest.raises(ValueError, match="varios enlaces pegados") as exc:
        csv_manual.leer_publicaciones(archivo(tmp_path, [fila]))
    assert "ABcd1234" not in str(exc.value)


def test_linkedin_activity_en_query(tmp_path, fila):
    fila.update(url="https://www.linkedin.com/posts/autor-ficticio_ejemplo-ugcPost-2234567890123456789-abcd?highlightedUpdateUrn=urn%3Ali%3Aactivity%3A1234567890123456789")
    p = csv_manual.leer_publicaciones(archivo(tmp_path, [fila]))[0]
    assert p.id == "li:1234567890123456789"
    assert p.autor_hash == calcular_autor_hash(Plataforma.LINKEDIN, "autor-ficticio", "sal_sintetica")


def test_cli_json(capsys):
    csv_manual.main([str(FIXTURES / "manual_comas.csv")])
    datos = json.loads(capsys.readouterr().out)
    assert len(datos["publicaciones"]) == 2
    assert "metricas" in datos


@pytest.mark.parametrize("valor,esperado", [("1200",1200), ("1.200",1200), ("1,2 mil",1200),
    ("12K",12000), ("12 mil",12000), ("1,5M",1500000), ("1.5 M",1500000),
    ("0",0), ("",None), ("1.234.567",1234567), ("0,001K",1)])
def test_numeros_metricas(tmp_path, fila, valor, esperado):
    fila.update(vistas=valor, reacciones="0", comentarios="", compartidos="2")
    publicaciones, metricas = csv_manual.leer_con_metricas(archivo(tmp_path, [fila]))
    assert len(publicaciones) == len(metricas) == 1
    m = metricas[0]
    assert (m.vistas, m.likes, m.comentarios, m.compartidos) == (esperado,0,None,2)
    assert m.publicacion_id == publicaciones[0].id
    assert m.capturada_en == publicaciones[0].capturada_en and m.origen == "csv_manual"


@pytest.mark.parametrize("valor", ["-1", "12.5", "1,2345 mil", "1,200", "1e3", "NaN", "12KK", "1.2.3", "dato_privado"])
def test_metricas_invalidas_sin_salida_parcial(tmp_path, fila, valor):
    filas = [{**fila, "vistas":"0"}, {**fila, "vistas":valor}, {**fila, "vistas":"-1"}]
    with pytest.raises(ValueError) as exc:
        csv_manual.leer_con_metricas(archivo(tmp_path, filas))
    assert "Línea 3" in str(exc.value) and "Línea 4" in str(exc.value)
    assert "vistas" in str(exc.value) and "dato_privado" not in str(exc.value)


def test_metricas_vacias_no_crean_fila(tmp_path, fila):
    publicaciones, metricas = csv_manual.leer_con_metricas(archivo(tmp_path, [fila]))
    assert len(publicaciones) == 1 and metricas == []


@pytest.mark.parametrize("fecha,esperada", [("2026-01-03",datetime(2026,1,3,tzinfo=timezone.utc)),
    ("3/01/2026",datetime(2026,1,3,tzinfo=timezone.utc)),
    ("2026-01-03T10:00:00-05:00",datetime(2026,1,3,15,tzinfo=timezone.utc))])
def test_fecha_captura_explicita(tmp_path, fila, fecha, esperada):
    fila.update(fecha_captura=fecha, reacciones="2")
    ps, ms = csv_manual.leer_con_metricas(archivo(tmp_path, [fila]))
    assert ps[0].capturada_en == ms[0].capturada_en == esperada


def test_metricas_sin_fecha_captura_es_error(tmp_path, fila):
    # Editar el CSV cambia su fecha de modificación: no sirve para fechar métricas.
    filas = [{**fila, "vistas": "3", "reacciones": "", "fecha_captura": ""},
             {**fila, "vistas": "", "reacciones": "", "fecha_captura": ""}]
    with pytest.raises(ValueError) as exc:
        csv_manual.leer_con_metricas(archivo(tmp_path, filas))
    assert "Línea 2: fecha_captura" in str(exc.value) and "Línea 3" not in str(exc.value)


def test_sin_metricas_la_captura_es_la_del_archivo(tmp_path, fila):
    fila.update(fecha_captura="")
    ruta = archivo(tmp_path, [fila])
    publicaciones, metricas = csv_manual.leer_con_metricas(ruta)
    assert metricas == []
    assert publicaciones[0].capturada_en == datetime.fromtimestamp(ruta.stat().st_mtime, timezone.utc)


@pytest.mark.parametrize("fecha", ["ayer", "2026-01-02T12:00:00", "2025-01-01"])
def test_fecha_captura_invalida(tmp_path, fila, fecha):
    fila.update(fecha_captura=fecha, vistas="1")
    with pytest.raises(ValueError, match="Línea 2"):
        csv_manual.leer_con_metricas(archivo(tmp_path, [fila]))


def test_cli_sin_salida_parcial(tmp_path, fila, capsys):
    ruta = archivo(tmp_path, [fila, {**fila,"formato":"invalido"}])
    with pytest.raises(SystemExit) as exc:
        csv_manual.main([str(ruta)])
    salida = capsys.readouterr()
    assert exc.value.code == 1 and salida.out == "" and "Línea 3" in salida.err
