import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from radar.recoleccion import buscar, tiktok_cuentas as tc
from radar.recoleccion.servicio import crear_app
from test_servicio import entorno_sin_red, esperar


def pares(dias=1, hashtag='ia', sufijo=0):
    ahora = datetime.now(timezone.utc)
    fecha = ahora - timedelta(days=dias)
    return tc.tiktok.convertir_entrada(dict(
        id=str((int(fecha.timestamp()) << 32) + sufijo), timestamp=fecha.timestamp(),
        description='Contenido sintético #' + hashtag, duration=30,
        uploader_id='ficticio', view_count=20), sal='sal-ficticia', ahora=ahora)


def cuerpo(*datos):
    return dict(publicaciones=[p.model_dump(mode='json') for p, _ in datos],
                metricas=[m.model_dump(mode='json') for _, m in datos if m is not None])


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv('RADAR_TOKEN', 'busqueda-ficticio')
    monkeypatch.setenv('CARGA_TOKEN', 'carga-ficticio')
    monkeypatch.setenv('TIKTOK_DESDE_CARGA', '1')
    monkeypatch.setattr(tc, 'capturar', lambda *a, **k: pytest.fail('No debe capturar'))
    with TestClient(crear_app()) as client:
        yield client


def cargar(client, datos):
    return client.post('/tiktok/carga', json=datos,
                       headers={'X-Carga-Token': 'carga-ficticio'})


def consultar(client, tema='#ia', redes=None, dias=7):
    r = client.post('/busquedas', json=dict(tema=tema, redes=redes or ['tiktok'], dias=dias),
                    headers={'X-Token': 'busqueda-ficticio'})
    assert r.status_code == 202
    client.headers['X-Token'] = 'busqueda-ficticio'
    try:
        return esperar(client, r.json()['id'])
    finally:
        client.headers.pop('X-Token')


def test_carga_token_reemplazo_y_estado_publico(cliente, monkeypatch):
    assert cliente.get('/tiktok/carga').json() == {'publicaciones': 0, 'cargado_en': None}
    datos = cuerpo(pares())
    for headers in ({}, {'X-Carga-Token': 'malo'}, {'X-Token': 'busqueda-ficticio'}):
        assert cliente.post('/tiktok/carga', json=datos, headers=headers).status_code == 401
    r = cargar(cliente, datos)
    assert r.status_code == 200
    assert r.json()['publicaciones'] == 1 and r.json()['cargado_en']
    assert cliente.get('/tiktok/carga').json() == r.json()
    assert cargar(cliente, cuerpo()).json()['publicaciones'] == 0
    monkeypatch.delenv('CARGA_TOKEN')
    assert cargar(cliente, datos).status_code == 503
    assert cliente.get('/salud').status_code == 200


@pytest.mark.parametrize('caso', ['youtube', 'metrica_ajena', 'sin_contrato', 'maximo', 'duplicado'])
def test_carga_invalida_conserva_anterior(cliente, caso):
    datos = cuerpo(pares())
    assert cargar(cliente, datos).status_code == 200
    if caso == 'youtube':
        datos['publicaciones'][0].update(id='yt:dQw4w9WgXcQ', plataforma='youtube')
    elif caso == 'metrica_ajena':
        datos['metricas'][0]['publicacion_id'] = 'li:1234567890123456789'
    elif caso == 'sin_contrato':
        datos['publicaciones'][0].pop('autor_hash')
    elif caso == 'maximo':
        datos['publicaciones'] *= 3001
    else:
        datos['publicaciones'] *= 2
    assert cargar(cliente, datos).status_code == 422
    assert cliente.get('/tiktok/carga').json()['publicaciones'] == 1


def test_busqueda_cargada_fecha_hashtag_y_metricas(cliente):
    buena, vieja, otro, futura = pares(), pares(10), pares(hashtag='otra', sufijo=1), pares()
    # Construir una publicación futura válida respecto a su propia captura.
    p, m = futura
    futura = (p.model_copy(update={'id': p.id[:-1] + '9',
        'publicada_en': datetime.now(timezone.utc) + timedelta(days=1),
        'capturada_en': datetime.now(timezone.utc) + timedelta(days=2)}), None)
    assert cargar(cliente, cuerpo(buena, vieja, otro, futura)).status_code == 200
    r = consultar(cliente)
    assert r['estado'] == 'lista'
    assert [p['id'] for p in r['publicaciones']] == [buena[0].id]
    assert [m['publicacion_id'] for m in r['metricas']] == [buena[0].id]
    assert r['resumen']['tiktok']['origen_tiktok'] == 'carga'
    assert r['resumen']['tiktok']['cargado_en'] == cliente.get('/tiktok/carga').json()['cargado_en']


def test_tema_comas_reutiliza_modelo(cliente, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'ficticia')
    pedidos = []
    def pedir(req):
        pedidos.append(json.loads(req.data))
        return {'choices': [{'message': {'content': '1: SI\n2: NO'}}]}
    monkeypatch.setattr(tc, '_pedir', pedir)
    original = tc.FiltroTema
    monkeypatch.setattr(tc, 'FiltroTema', lambda tema, **kw: original(tema, clave=kw['clave']))
    assert cargar(cliente, cuerpo(pares(sufijo=1), pares(sufijo=2))).status_code == 200
    r = consultar(cliente, tema='educación, robótica')
    assert len(r['publicaciones']) == 1
    assert 'educación; robótica' in pedidos[0]['messages'][0]['content']


def test_sin_carga_fallida_y_otras_redes(cliente, monkeypatch):
    llamadas = []
    monkeypatch.setattr(buscar, '_youtube', lambda *a: (llamadas.append('youtube') or [], []))
    monkeypatch.setattr(buscar, '_linkedin', lambda *a: (llamadas.append('linkedin') or [], []))
    r = consultar(cliente, redes=['youtube', 'linkedin', 'tiktok'])
    assert llamadas == ['youtube'] * 5 + ['linkedin']
    assert r['resumen']['tiktok']['fallidas'] == 1
    assert r['resumen']['tiktok']['aviso'] == 'No hay datos de TikTok cargados'
    r = consultar(cliente)
    assert r['resumen']['tiktok']['fallidas'] == 1
    assert r['publicaciones'] == []


def test_sin_bandera_conserva_captura(cliente, monkeypatch):
    monkeypatch.delenv('TIKTOK_DESDE_CARGA')
    llamadas = []
    monkeypatch.setattr(buscar, '_tiktok', lambda *a: (llamadas.append(a) or [], []))
    assert consultar(cliente)['estado'] == 'lista'
    assert llamadas == [('#ia', 7)]


@pytest.mark.parametrize('vacia,detenida,interrumpida', [(True, False, False), (False, True, False),
                                                       (False, False, True)])
def test_subida_no_borra_lo_bueno(monkeypatch, capsys, vacia, detenida, interrumpida):
    p, m = pares()
    monkeypatch.setattr(tc, 'capturar', lambda *a, **kw: (
        [] if vacia else [p], [] if vacia else [m],
        {'detenido': detenida, 'interrumpido': interrumpida}))
    tc.subir(['cuenta_ficticia'], servicio='https://ejemplo.invalid', sal='sal', token='ficticio',
             pedir=lambda *a, **kw: pytest.fail('No debe subir'))
    assert 'No se sube' in capsys.readouterr().err


def test_subida_repite_y_no_filtra(monkeypatch, capsys):
    p, m = pares()
    capturas, pedidos, pausas = [], [], []
    def capturar(*a, **kw):
        capturas.append(kw)
        return [p], [m], {'detenido': False, 'interrumpido': False}
    def pedir(req, **kw):
        pedidos.append((req, kw))
    def pausa(segundos):
        pausas.append(segundos)
        if len(pausas) == 2:
            raise KeyboardInterrupt
    monkeypatch.setattr(tc, 'capturar', capturar)
    tc.subir(['cuenta_ficticia'], servicio='https://ejemplo.invalid/', sal='sal', token='ficticio',
             dias=4, cada_minutos=15, pedir=pedir, pausa=pausa)
    assert len(capturas) == len(pedidos) == 2
    assert all(c['dias'] == 4 and c.get('filtro') is None for c in capturas)
    assert pausas == [900, 900]
    req, opciones = pedidos[0]
    assert req.full_url == 'https://ejemplo.invalid/tiktok/carga'
    assert req.get_header('X-carga-token') == 'ficticio'
    assert json.loads(req.data) == cuerpo((p, m))
    assert opciones['timeout'] > 0
    assert 'ficticio' not in capsys.readouterr().err


def test_cli_subir(monkeypatch):
    monkeypatch.setenv('TIKTOK_CUENTAS', 'cuenta_ficticia')
    monkeypatch.setenv('CARGA_TOKEN', 'ficticio')
    monkeypatch.setenv('AUTOR_HASH_SAL', 'sal')
    llamadas = []
    monkeypatch.setattr(tc, 'subir', lambda *a, **kw: llamadas.append((a, kw)))
    tc.main(['subir', '--servicio', 'https://ejemplo.invalid', '--dias', '4', '--cada-minutos', '15'])
    assert llamadas == [((['cuenta_ficticia'],), dict(servicio='https://ejemplo.invalid',
        dias=4, cada_minutos=15, sal='sal', token='ficticio'))]
