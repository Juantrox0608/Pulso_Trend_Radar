import pytest

from radar.contrato import Plataforma, id_contrato, id_desde_url, url_canonica


@pytest.mark.parametrize(
    ("url", "plataforma", "id_nativo"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s", Plataforma.YOUTUBE, "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", Plataforma.YOUTUBE, "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", Plataforma.YOUTUBE, "dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", Plataforma.YOUTUBE, "dQw4w9WgXcQ"),
        ("https://www.tiktok.com/@cuenta/video/7667873615114964244?lang=es", Plataforma.TIKTOK, "7667873615114964244"),
        (
            "https://www.linkedin.com/posts/nombre-apellido_looking-ahead-to-2026-activity-7411490079984250880-Vb5v",
            Plataforma.LINKEDIN,
            "7411490079984250880",
        ),
        (
            "https://www.linkedin.com/feed/update/urn:li:activity:7411490079984250880/",
            Plataforma.LINKEDIN,
            "7411490079984250880",
        ),
    ],
)
def test_extrae_id_nativo_de_urls_pegadas(url, plataforma, id_nativo):
    assert id_desde_url(url) == (plataforma, id_nativo)


def test_acepta_link_corto_de_linkedin():
    plataforma, id_nativo = id_desde_url("https://lnkd.in/e/aB3d-f_9")

    assert plataforma is Plataforma.LINKEDIN
    assert id_contrato(plataforma, id_nativo) == "li:lnkd-e-aB3d-f_9"
    assert url_canonica(plataforma, id_nativo) == "https://lnkd.in/e/aB3d-f_9"


@pytest.mark.parametrize(
    "url",
    ["https://lnkd.in/e/abc1https://lnkd.in/e/abcd1234", "https://lnkd.in/", "https://lnkd.in/e/"],
)
def test_rechaza_link_corto_roto(url):
    with pytest.raises(ValueError, match="No se encontró el id"):
        id_desde_url(url)


def test_url_canonica_no_lleva_autor():
    _, id_nativo = id_desde_url(
        "https://www.linkedin.com/posts/nombre-apellido_tema-activity-7411490079984250880-Vb5v"
    )

    canonica = url_canonica(Plataforma.LINKEDIN, id_nativo)

    assert "nombre-apellido" not in canonica
    assert canonica == "https://www.linkedin.com/feed/update/urn:li:activity:7411490079984250880/"


def test_rechaza_url_de_otro_sitio():
    with pytest.raises(ValueError, match="no es de YouTube, TikTok ni LinkedIn"):
        id_desde_url("https://example.com/post/1")


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/@cuenta",
        "https://www.linkedin.com/in/nombre-apellido/",
        "https://www.youtube.com/@canal",
    ],
)
def test_rechaza_urls_de_perfil_sin_publicacion(url):
    with pytest.raises(ValueError, match="No se encontró el id"):
        id_desde_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://vm.tiktok.com/ZMabc123/",
        "https://www.tiktok.com/t/ZTabc123/",
        "https://www.linkedin.com/feed/update/urn:li:ugcPost:7380123456789012345/",
        "https://www.linkedin.com/feed/update/urn:li:share:7380123456789012345/",
    ],
)
def test_links_compartidos_desde_la_app_explican_que_hacer(url):
    with pytest.raises(ValueError, match="copia la url completa"):
        id_desde_url(url)


def test_id_contrato_agrega_prefijo():
    assert id_contrato(Plataforma.TIKTOK, "7667873615114964244") == "tt:7667873615114964244"


def test_id_contrato_valida_formato():
    with pytest.raises(ValueError, match="id nativo inválido"):
        id_contrato(Plataforma.YOUTUBE, "corto")
