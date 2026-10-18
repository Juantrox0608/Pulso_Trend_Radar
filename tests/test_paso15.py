import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
from yt_dlp.utils import DownloadError, ExtractorError

from radar.recoleccion import linkedin_buscar as lb, tiktok_cuentas as tc
from radar.recoleccion.presupuesto_busqueda import PresupuestoBusqueda


@pytest.mark.parametrize('error,categoria', [
    *[(HTTPError('https://usuario.test', c, 'usuario', {}, None), nombre)
      for c, nombre in [(403, 'http_403'), (429, 'http_429'), (500, 'http_otro')]],
    (TimeoutError('usuario'), 'tiempo_agotado'),
    (URLError(TimeoutError('usuario')), 'tiempo_agotado'),
    (ExtractorError('usuario'), 'extractor'),
    (RuntimeError('usuario'), 'otro'),
    (DownloadError('usuario HTTP Error 403'), 'http_403'),
    (DownloadError('usuario HTTP Error 429'), 'http_429'),
    (DownloadError('usuario HTTP Error 502'), 'http_otro'),
    (DownloadError('usuario timed out'), 'tiempo_agotado'),
    (DownloadError('Unable to extract usuario'), 'extractor'),
    (DownloadError('usuario', exc_info=(ExtractorError, ExtractorError('usuario'), None)), 'extractor'),
    (DownloadError('usuario', exc_info=(URLError, URLError(TimeoutError('usuario')), None)), 'tiempo_agotado'),
])
def test_tiktok_diagnostico_seguro(error, categoria, capsys):
    def listar(*_):
        raise error
    _, _, r = tc.capturar(['canal_privado_123'], sal='sal', listar=listar)
    stderr = capsys.readouterr().err
    assert r['motivos_fallo'] == {categoria: 1}
    assert len(stderr.splitlines()) == 1 and categoria in stderr
    assert type(error).__name__ in stderr
    for privado in ('canal_privado_123', 'usuario', 'https://'):
        assert privado not in stderr + str(r)


@pytest.mark.parametrize('entradas', [[], [{}], None])
def test_tiktok_sin_datos(entradas, capsys):
    _, _, r = tc.capturar(['canal_privado_123'], sal='sal', listar=lambda *_: entradas)
    assert r['motivos_fallo'] == {'sin_datos': 1}
    assert r['cuentas_fallidas'] == 1
    assert 'sin_datos' in capsys.readouterr().err


@pytest.mark.parametrize('dias,inicial,esperadas', [(7, 'vieja', 2), (7, 'vacia', 2),
                                                  (7, 'reciente', 1), (None, 'vacia', 1)])
def test_linkedin_consulta_extra(tmp_path, monkeypatch, dias, inicial, esperadas):
    monkeypatch.setattr(lb, '_presupuesto', PresupuestoBusqueda(tmp_path/'gasto.json'))
    ahora = datetime.now(timezone.utc)
    def url(d):
        return f'https://www.linkedin.com/feed/update/urn:li:activity:{int((ahora-timedelta(days=d)).timestamp()*1000)<<22}/'
    vieja, reciente = url(20), url(1)
    pedidos, abiertas = [], []
    def pedir(req):
        pedidos.append(json.loads(req.data)['messages'][0]['content'])
        urls = ([vieja] if inicial == 'vieja' else [reciente] if inicial == 'reciente' else []) if len(pedidos) == 1 else [vieja, reciente]
        return {'choices': [{'message': {'annotations': [{'url_citation': {'url': u}} for u in urls]}}], 'usage': {'cost': 0.007}}
    html = (Path(__file__).parent/'fixtures/linkedin_post.html').read_text(encoding='utf-8').replace(
        '2026-01-02T10:00:00-05:00', (ahora-timedelta(days=1)).isoformat())
    def obtener(u):
        abiertas.append(u)
        return u, html
    ps, _, r = lb.descubrir(['IA'], clave='ficticia', sal='sal', dias=dias,
                            pedir=pedir, obtener=obtener, pausa=lambda _: None)
    assert len(pedidos) == esperadas and r['consultas_extra'] == esperadas-1
    assert r['consultas'] == esperadas
    assert len(abiertas) == len(set(abiertas))
    if esperadas == 2:
        assert pedidos[0] != pedidos[1] and '7' in pedidos[1] and 'IA' in pedidos[1]
        assert len(ps) == 1 and abiertas == [reciente]


@pytest.mark.parametrize('groq', [False, True])
def test_linkedin_extra_respeta_presupuesto_y_respaldo(tmp_path, monkeypatch, groq):
    presupuesto = PresupuestoBusqueda(tmp_path/'gasto.json', maximo=1)
    monkeypatch.setattr(lb, '_presupuesto', presupuesto)
    if groq:
        monkeypatch.setenv('GROQ_API_KEY', 'ficticia')
    pedidos = []
    def pedir(req):
        pedidos.append(req.full_url)
        if 'groq.com' in req.full_url:
            return {'choices': [{'message': {'content': ''}}], 'usage': {'total_tokens': 10}}
        return {'choices': [{'message': {'annotations': []}}], 'usage': {'cost': 0.007}}
    monkeypatch.setattr(lb, '_pedir', pedir)
    ps, ms, r = lb.descubrir(['IA'], clave='ficticia', sal='sal', dias=7)
    assert ps == ms == [] and presupuesto.intentos == 1
    assert r['consultas_extra'] == 1 and r['consultas'] == 2
    assert float(r['costo_usd']) == 0.007
    assert len(pedidos) == (2 if groq else 1)
    assert r['groq_tokens'] == (10 if groq else 0)
    assert r['consultas_fallidas'] == (0 if groq else 1)


def test_linkedin_extra_no_repite_url_ni_amplia_ventana(monkeypatch):
    url = 'https://lnkd.in/X/Ficticio'
    llamadas, consultas = [], []
    def buscar(consulta, **kw):
        consultas.append(consulta)
        return [url], 0
    monkeypatch.setattr(lb, 'buscar_urls', buscar)
    html = (Path(__file__).parent/'fixtures/linkedin_post.html').read_text(encoding='utf-8')
    def obtener(u):
        llamadas.append(u)
        return 'https://www.linkedin.com/feed/update/urn:li:activity:2234567890123456789/', html
    ps, ms, r = lb.descubrir(['IA'], clave='ficticia', sal='sal', dias=7, obtener=obtener)
    assert ps == ms == [] and llamadas == [url]
    assert len(consultas) == 2 and r['consultas_extra'] == 1 and r['urls'] == 1


def test_tiktok_suma_motivos_y_una_linea_por_fallo(capsys):
    _, _, r = tc.capturar(['canal_001', 'canal_002', 'canal_003', 'canal_004'],
                          sal='sal', listar=lambda *_: [], pausa=lambda _: None)
    assert r['motivos_fallo'] == {'sin_datos': 3} and r['detenido']
    assert len(capsys.readouterr().err.splitlines()) == 3


def test_busqueda_suma_consultas_extra_entre_terminos():
    from radar.recoleccion.buscar import recolectar
    def linkedin(*_):
        return [], [], {'consultas': 2, 'consultas_extra': 1}
    _, _, r = recolectar('IA, educación', redes=['linkedin'], recolectores={'linkedin': linkedin})
    assert r['linkedin']['detalle']['consultas_extra'] == 2
