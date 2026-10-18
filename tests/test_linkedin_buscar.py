import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from radar.recoleccion import linkedin_buscar as buscar

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://www.linkedin.com/posts/autorficticio_ia-activity-2234567890123456789-abcd"


def url(numero):
    return f"https://www.linkedin.com/feed/update/urn:li:activity:{2234567890123456789 + numero}/"


def respuesta(urls):
    return {"choices": [{"message": {"annotations": [
        {"url_citation": {"url": u}} for u in urls]}}], "usage": {"cost": 0.007}}


@pytest.fixture(autouse=True)
def sin_red(monkeypatch, tmp_path):
    from radar.recoleccion.presupuesto_busqueda import PresupuestoBusqueda
    monkeypatch.setattr(buscar, '_presupuesto', PresupuestoBusqueda(tmp_path/'gasto_ficticio.json'))
    monkeypatch.setattr("socket.socket.connect", lambda *a: pytest.fail("Red prohibida"))


def test_busqueda_cuerpo_y_filtrado():
    llamadas = []
    def pedir(request):
        llamadas.append(request)
        return json.loads((FIXTURES / "linkedin_busqueda.json").read_text(encoding="utf-8"))
    urls, costo = buscar.buscar_urls("IA en español", clave="clave_ficticia", pedir=pedir)
    assert urls == [URL, url(1)]
    assert costo == Decimal("0.007")
    assert len(llamadas) == 1
    request = llamadas[0]
    assert request.full_url == "https://openrouter.ai/api/v1/chat/completions"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer clave_ficticia"
    assert json.loads(request.data) == {
        "model": "deepseek/deepseek-v4-flash-0731", "reasoning": {"enabled": False}, "max_tokens": 300,
        "plugins": [{"id": "web", "engine": "exa", "max_results": 10,
                     "include_domains": ["linkedin.com"], "search_prompt": "Resultados:"}],
        "messages": [{"role": "user", "content": "IA en español"}]}


def test_transporte_timeout_y_json(monkeypatch):
    class Respuesta:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return json.dumps(respuesta([])).encode()
    def abrir(request, *, timeout):
        assert timeout == 20
        return Respuesta()
    monkeypatch.setattr(buscar, "urlopen", abrir)
    assert buscar.buscar_urls("IA", clave="ficticia") == ([], Decimal("0.007"))


@pytest.mark.parametrize("error", [HTTPError("https://ficticio.test/clave_ficticia", 401,
    "Nombre Exa clave_ficticia", {}, None), URLError("clave_ficticia"), ValueError("clave_ficticia")])
def test_errores_seguros(error):
    def pedir(_): raise error
    with pytest.raises(ValueError, match="OpenRouter") as exc:
        buscar.buscar_urls("IA", clave="clave_ficticia", pedir=pedir)
    assert "clave_ficticia" not in str(exc.value)
    assert "Nombre Exa" not in str(exc.value)


@pytest.mark.parametrize("valor", [{}, {"choices": []}, {"choices": [{"message": {}}]},
    {"choices": [{"message": {"annotations": []}}], "usage": {"cost": "NaN"}},
    {"choices": [{"message": {"annotations": []}}], "usage": {"cost": -1}}])
def test_respuesta_invalida(valor):
    with pytest.raises(ValueError, match="OpenRouter"):
        buscar.buscar_urls("IA", clave="ficticia", pedir=lambda _: valor)


def test_deduplica_por_id_y_limita_resultados():
    urls, _ = buscar.buscar_urls("IA", clave="ficticia", max_resultados=2,
        pedir=lambda _: respuesta([URL, url(0), url(1), url(2)]))
    assert urls == [URL, url(1)]


def pagina(fecha=None):
    html = (FIXTURES / "linkedin_post.html").read_text(encoding="utf-8")
    return html.replace("2026-01-02T10:00:00-05:00", (fecha or datetime.now(timezone.utc)).isoformat())


def url_fecha(fecha):
    return f"https://www.linkedin.com/feed/update/urn:li:activity:{int(fecha.timestamp() * 1000) << 22}/"


def test_fecha_desde_id_en_utc_y_alternativas_sin_fecha():
    fecha = datetime(2026, 10, 17, 12, 34, 56, 789000, tzinfo=timezone.utc)
    identificador = str((int(fecha.timestamp() * 1000) << 22) + 123)
    assert buscar._fecha_desde_id(identificador) == fecha
    assert buscar._fecha_desde_id("lnkd-X-Ficticio") is None
    assert buscar._fecha_desde_id("9" * 22) is None


def test_filtro_id_incluye_limite_exacto_y_cuenta_todas_las_antiguas(monkeypatch):
    ahora = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    class Reloj(datetime):
        @classmethod
        def now(cls, tz=None): return ahora
    monkeypatch.setattr(buscar, "datetime", Reloj)
    limite = ahora - timedelta(days=7)
    vieja = url_fecha(limite - timedelta(milliseconds=1))
    vigente = url_fecha(limite)
    otra_vieja = url_fecha(limite - timedelta(days=1))
    llamadas = []
    def obtener(u):
        llamadas.append(u)
        return u, pagina(limite)
    p, m, resumen = buscar.descubrir(["IA"], clave="ficticia", sal="sal", dias=7, maximo=1,
        pedir=lambda _: respuesta([vieja, vigente, otra_vieja]), obtener=obtener)
    assert llamadas == [vigente] and len(p) == 1 and resumen["fuera_fecha"] == 2


@pytest.mark.parametrize("dias", [None, 7])
def test_consulta_con_periodo_y_mes_en_espanol(monkeypatch, dias):
    class Reloj(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 17, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(buscar, "datetime", Reloj)
    consultas = []
    def pedir(request):
        consultas.append(json.loads(request.data)["messages"][0]["content"])
        return respuesta([])
    buscar.descubrir(["IA", "automatización"], clave="ficticia", sal="sal", dias=dias, pedir=pedir)
    prefijo = "publicaciones de los últimos 7 días (octubre de 2026) en LinkedIn: " if dias else ""
    assert consultas[:2] == [prefijo + "IA", prefijo + "automatización"]
    assert len(consultas) == (3 if dias else 2)


def test_filtra_id_antes_de_consultar_sin_gastar_tope_ni_pausas():
    ahora = datetime.now(timezone.utc)
    antigua = url_fecha(ahora - timedelta(days=8))
    reciente = url_fecha(ahora - timedelta(days=1))
    llamadas = []
    def obtener(u):
        llamadas.append(u)
        return u, pagina()
    p, m, resumen = buscar.descubrir(["IA"], clave="ficticia", sal="sal", dias=7, maximo=1,
        pedir=lambda _: respuesta([antigua, reciente]), obtener=obtener,
        pausa=lambda _: pytest.fail("No hay pausa antes del primer intento"))
    assert llamadas == [reciente] and len(p) == len(m) == 1
    assert resumen["fuera_fecha"] == 1 and resumen["completados"] == 1 and resumen["urls"] == 2


def test_id_no_numerico_conserva_filtro_por_publicada_en(monkeypatch):
    corta = "https://lnkd.in/X/Ficticio"
    monkeypatch.setattr(buscar, "buscar_urls", lambda *a, **kw: ([corta], Decimal("0.007")))
    llamadas = []
    def obtener(u):
        llamadas.append(u)
        return URL, pagina(datetime.now(timezone.utc) - timedelta(days=8))
    p, m, resumen = buscar.descubrir(["IA"], clave="ficticia", sal="sal", dias=7, obtener=obtener)
    assert llamadas == [corta] and p == m == []
    assert resumen["fuera_fecha"] == resumen["completados"] == 1


def test_consulta_fallida_continua_y_resume_sin_datos_privados(monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "ficticia")
    monkeypatch.setenv("AUTOR_HASH_SAL", "sal")
    consultas = []
    def pedir(request):
        consulta = json.loads(request.data)["messages"][0]["content"]
        consultas.append(consulta)
        if consulta == "falla":
            raise ValueError("clave_privada nombre_privado")
        return respuesta([URL])
    monkeypatch.setattr(buscar, "_pedir", pedir)
    monkeypatch.setattr(buscar.linkedin, "_obtener", lambda u: (u, pagina()))
    buscar.main(["--consulta", "falla", "--consulta", "IA"])
    salida = capsys.readouterr()
    assert consultas == ["falla", "IA"]
    assert len(json.loads(salida.out)["publicaciones"]) == 1
    assert "Consultas: 2" in salida.err and "consultas fallidas: 1" in salida.err
    assert "USD 0.007000" in salida.err and "privad" not in salida.err + salida.out


def test_todas_las_consultas_fallidas_no_abren_linkedin():
    llamadas = []
    def pedir(request):
        llamadas.append(request)
        raise ValueError("dato_privado")
    with pytest.raises(ValueError, match="OpenRouter") as exc:
        buscar.descubrir(["IA", "automatización"], clave="ficticia", sal="sal", pedir=pedir,
            obtener=lambda _: pytest.fail("No debe consultar LinkedIn"))
    assert len(llamadas) == 2 and "dato_privado" not in str(exc.value)


def test_descubrir_omite_filtra_y_conserva_privacidad():
    URL = url_fecha(datetime.now(timezone.utc) - timedelta(days=1))
    base = int(URL.rstrip('/').rsplit(':', 1)[1])
    def url(numero):
        return f"https://www.linkedin.com/feed/update/urn:li:activity:{base + numero}/"
    peticiones, obtenidas, pausas = [], [], []
    def pedir(request):
        peticiones.append(request)
        return respuesta([URL, url(0), url(1), url(2), url(3)])
    def obtener(u):
        obtenidas.append(u)
        if u == url(1): raise ValueError("Nombre Exa clave_ficticia")
        fecha = datetime.now(timezone.utc) - timedelta(days=30) if u == url(2) else None
        return u, pagina(fecha)
    publicaciones, metricas, resumen = buscar.descubrir(["IA", "IA en LatAm"], clave="ficticia", sal="sal",
        dias=7, pedir=pedir, obtener=obtener, pausa=pausas.append)
    assert [p.id for p in publicaciones] == [f"li:{base}", f"li:{base + 3}"]
    assert len(metricas) == 2 and len(peticiones) == 2
    assert obtenidas == [URL, url(1), url(2), url(3)]
    assert pausas == [3, 3, 3]
    assert resumen["consultas"] == 2 and resumen["urls"] == 4
    assert resumen["completados"] == 3 and resumen["omitidos"] == 1 and resumen["fuera_fecha"] == 1
    assert resumen["costo_usd"] == Decimal("0.014")
    salida = str(resumen) + "".join(p.model_dump_json() for p in publicaciones)
    for dato in ("autorficticio", "Nombre Ficticio", "mencion_ficticia", "Nombre Exa", "<script"):
        assert dato not in salida
    assert "@[usuario]" in publicaciones[0].texto


@pytest.mark.parametrize("bloqueo", [429, 999, "authwall"])
def test_bloqueo_corta_y_devuelve_lo_reunido(bloqueo):
    llamadas, pausas = [], []
    def obtener(u):
        llamadas.append(u)
        if u == url(1):
            if bloqueo == "authwall": return "https://www.linkedin.com/authwall", ""
            raise HTTPError(u, bloqueo, "dato_privado", {}, None)
        return u, pagina()
    publicaciones, metricas, resumen = buscar.descubrir(["IA"], clave="ficticia", sal="sal",
        pedir=lambda _: respuesta([URL, url(1), url(2)]), obtener=obtener, pausa=pausas.append)
    assert len(publicaciones) == len(metricas) == 1
    assert llamadas == [URL, url(1)] and pausas == [3]
    assert "bloqueo" in resumen["aviso"].lower()
    assert "dato_privado" not in str(resumen)


def test_tope_100_intentos_incluso_si_fallan():
    llamadas, pausas = [], []
    def pedir(request):
        numero = int(json.loads(request.data)["messages"][0]["content"])
        return respuesta([url(numero * 10 + n) for n in range(10)])
    def obtener(u):
        llamadas.append(u)
        raise ValueError("post caído")
    p, m, resumen = buscar.descubrir(map(str, range(20)), clave="ficticia", sal="sal",
        pedir=pedir, obtener=obtener, pausa=pausas.append)
    assert p == m == [] and len(llamadas) == 100 and pausas == [3] * 99
    assert resumen["urls"] == 200 and resumen["omitidos"] == 100


@pytest.mark.parametrize("opciones", [{"consultas": ["IA"] * 21}, {"maximo": 101}, {"maximo": 0},
    {"dias": 0}, {"dias": -1}, {"consultas": []}, {"consultas": [" "]}, {"sal": ""},
    {"max_resultados": 11}, {"max_resultados": 0}])
def test_limites_antes_de_cualquier_peticion(opciones):
    argumentos = {"consultas": ["IA"], "clave": "ficticia", "sal": "sal"} | opciones
    with pytest.raises(ValueError):
        buscar.descubrir(**argumentos, pedir=lambda _: pytest.fail("No debe consultar"))


def test_cli_json_y_resumen(monkeypatch, capsys):
    URL = url_fecha(datetime.now(timezone.utc) - timedelta(days=1))
    monkeypatch.setenv("OPENROUTER_API_KEY", "clave_ficticia")
    monkeypatch.setenv("AUTOR_HASH_SAL", "sal")
    monkeypatch.setattr(buscar, "_pedir", lambda _: respuesta([URL]))
    monkeypatch.setattr(buscar.linkedin, "_obtener", lambda u: (u, pagina()))
    buscar.main(["--consulta", "IA", "--dias", "7", "--max", "1", "--resultados", "2"])
    salida = capsys.readouterr()
    datos = json.loads(salida.out)
    assert len(datos["publicaciones"]) == len(datos["metricas"]) == 1
    assert "Consultas: 1" in salida.err and "USD 0.007" in salida.err
    assert "clave_ficticia" not in salida.out + salida.err


@pytest.mark.parametrize("variable", ["OPENROUTER_API_KEY", "AUTOR_HASH_SAL"])
def test_cli_error_sin_credenciales(monkeypatch, capsys, variable):
    monkeypatch.setenv("OPENROUTER_API_KEY", "ficticia")
    monkeypatch.setenv("AUTOR_HASH_SAL", "ficticia")
    monkeypatch.delenv(variable)
    with pytest.raises(SystemExit) as exc:
        buscar.main(["--consulta", "IA"])
    assert exc.value.code == 1
    salida = capsys.readouterr()
    assert variable in salida.err and not salida.out


def test_cli_help_sin_credenciales(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        buscar.main(["--help"])
    assert exc.value.code == 0


def test_sin_resultados_no_consulta_linkedin():
    p, m, resumen = buscar.descubrir(["IA"], clave="ficticia", sal="sal",
        pedir=lambda _: respuesta([]), obtener=lambda _: pytest.fail("Sin posts no hay consultas"))
    assert p == m == [] and resumen["urls"] == 0
    assert resumen["costo_usd"] == Decimal("0.007")


def test_tope_configurado_y_post_sin_metricas():
    llamadas = []
    def obtener(u):
        llamadas.append(u)
        return u, '<script type="application/ld+json">' + json.dumps({
            "@type": "SocialMediaPosting", "text": "IA", "author": {"name": "Nombre Ficticio"},
            "datePublished": datetime.now(timezone.utc).isoformat()}) + '</script>'
    p, m, resumen = buscar.descubrir(["IA"], clave="ficticia", sal="sal", maximo=1,
        pedir=lambda _: respuesta([URL, url(1)]), obtener=obtener, pausa=lambda _: pytest.fail("Sin pausa inicial"))
    assert len(p) == 1 and m == [] and llamadas == [URL]
    assert resumen["completados"] == 1


def test_dias_no_acepta_publicaciones_futuras():
    URL = url_fecha(datetime.now(timezone.utc) - timedelta(days=1))
    p, m, resumen = buscar.descubrir(["IA"], clave="ficticia", sal="sal", dias=7,
        pedir=lambda _: respuesta([URL]), obtener=lambda u: (u, pagina(datetime.now(timezone.utc) + timedelta(days=1))))
    assert p == m == [] and resumen["omitidos"] == 1


def test_deduplica_destinos_tras_redireccion():
    p, m, resumen = buscar.descubrir(["IA"], clave="ficticia", sal="sal",
        pedir=lambda _: respuesta([URL, url(1)]), obtener=lambda u: (URL, pagina()), pausa=lambda _: None)
    assert len(p) == len(m) == 1 and resumen["completados"] == 2
