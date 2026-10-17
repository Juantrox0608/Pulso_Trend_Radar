from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from radar.contrato import Formato, Origen, Plataforma, Publicacion, calcular_autor_hash

AHORA = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def datos_validos(**cambios: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "yt:dQw4w9WgXcQ",
        "plataforma": "youtube",
        "titulo": "Agentes de IA para gerentes",
        "formato": "video_largo",
        "idioma": "es",
        "pais": "MX",
        "tipo_autor": "experto",
        "autor_hash": calcular_autor_hash(Plataforma.YOUTUBE, "UC123", sal="prueba"),
        "publicada_en": AHORA - timedelta(days=2),
        "capturada_en": AHORA,
        "origen": "api_oficial",
    }
    return {**base, **cambios}


def test_publicacion_valida_se_crea_con_version():
    pub = Publicacion(**datos_validos())

    assert pub.schema_version == "1.0"
    assert pub.formato is Formato.VIDEO_LARGO
    assert pub.origen is Origen.API_OFICIAL


def test_es_inmutable():
    pub = Publicacion(**datos_validos())

    with pytest.raises(ValidationError):
        pub.titulo = "otro"


def test_rechaza_campos_extra_como_nombre_de_autor():
    with pytest.raises(ValidationError):
        Publicacion(**datos_validos(autor_nombre="Ana Pérez"))


def test_rechaza_id_con_prefijo_de_otra_plataforma():
    with pytest.raises(ValidationError, match="debe empezar con 'yt:'"):
        Publicacion(**datos_validos(id="tt:7667873615114964244"))


def test_rechaza_id_nativo_con_formato_incorrecto():
    with pytest.raises(ValidationError, match="formato de tiktok"):
        Publicacion(**datos_validos(id="tt:abc", plataforma="tiktok"))


@pytest.mark.parametrize(
    ("plataforma", "id_", "esperada"),
    [
        ("youtube", "yt:dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("tiktok", "tt:7667873615114964244", "https://www.tiktok.com/@/video/7667873615114964244"),
        (
            "linkedin",
            "li:7411490079984250880",
            "https://www.linkedin.com/feed/update/urn:li:activity:7411490079984250880/",
        ),
    ],
)
def test_url_canonica_se_arma_desde_el_id(plataforma, id_, esperada):
    pub = Publicacion(**datos_validos(plataforma=plataforma, id=id_))

    assert pub.url == esperada


def test_url_recibida_con_autor_se_ignora():
    pub = Publicacion(
        **datos_validos(
            plataforma="tiktok",
            id="tt:7667873615114964244",
            url="https://www.tiktok.com/@cuenta_real/video/7667873615114964244",
        )
    )

    assert "cuenta_real" not in pub.url
    assert "cuenta_real" not in pub.model_dump_json()


def test_exige_titulo_o_texto():
    with pytest.raises(ValidationError, match="título o texto"):
        Publicacion(**datos_validos(titulo=None, texto=None))


def test_rechaza_fecha_sin_zona_horaria():
    with pytest.raises(ValidationError):
        Publicacion(**datos_validos(publicada_en=datetime(2026, 10, 15, 9, 0)))


def test_convierte_fechas_a_utc():
    bogota = timezone(timedelta(hours=-5))
    pub = Publicacion(**datos_validos(publicada_en=datetime(2026, 10, 15, 7, 0, tzinfo=bogota)))

    assert pub.publicada_en == datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def test_rechaza_captura_anterior_a_publicacion():
    with pytest.raises(ValidationError, match="capturada_en"):
        Publicacion(**datos_validos(capturada_en=AHORA - timedelta(days=5)))


def test_normaliza_hashtags():
    pub = Publicacion(**datos_validos(hashtags=("#IA", "agentesIA", "#ia", " ")))

    assert pub.hashtags == ("ia", "agentesia")


@pytest.mark.parametrize(
    ("idioma", "esperado"),
    [("es-419", "es"), ("pt-BR", "pt"), ("EN", "en"), ("zxx", None), ("", None)],
)
def test_normaliza_idioma_de_youtube(idioma, esperado):
    pub = Publicacion(**datos_validos(idioma=idioma))

    assert pub.idioma == esperado


def test_pais_en_minusculas_se_pasa_a_mayusculas():
    pub = Publicacion(**datos_validos(pais=" mx "))

    assert pub.pais == "MX"


@pytest.mark.parametrize("pais", ["MEX", "M"])
def test_rechaza_codigo_de_pais_invalido(pais):
    with pytest.raises(ValidationError):
        Publicacion(**datos_validos(pais=pais))


def test_autor_hash_es_estable_y_no_revela_el_id():
    primero = calcular_autor_hash(Plataforma.TIKTOK, "usuario_123", sal="s")
    segundo = calcular_autor_hash(Plataforma.TIKTOK, "usuario_123", sal="s")

    assert primero == segundo
    assert len(primero) == 16
    assert "usuario_123" not in primero


def test_autor_hash_exige_sal():
    with pytest.raises(ValueError, match="sal"):
        calcular_autor_hash(Plataforma.LINKEDIN, "x", sal="")


def test_json_de_ida_y_vuelta_incluye_url():
    pub = Publicacion(**datos_validos())
    json_ = pub.model_dump_json()

    assert '"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"' in json_
    assert Publicacion.model_validate_json(json_) == pub
