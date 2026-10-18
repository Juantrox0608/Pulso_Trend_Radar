import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, local
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from radar.recoleccion.servicio import crear_app
from radar.recoleccion import tiktok_cuentas
from radar.recoleccion.youtube import buscar_con_metricas


@pytest.fixture(autouse=True)
def entorno_sin_red(monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    monkeypatch.delenv('TIKTOK_CUENTAS', raising=False)
    conectar, par = socket.socket.connect, socket.socketpair
    interno = local()
    def sin_red(sock, direccion):
        if getattr(interno, 'socketpair', False):
            return conectar(sock, direccion)
        pytest.fail('Red prohibida en las pruebas')
    def socketpair(*args, **kwargs):
        # asyncio usa un par local para despertar su bucle en Windows.
        interno.socketpair = True
        try:
            return par(*args, **kwargs)
        finally:
            interno.socketpair = False
    monkeypatch.setattr(socket.socket, 'connect', sin_red)
    monkeypatch.setattr(socket, 'socketpair', socketpair)
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('Red prohibida'))


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv('RADAR_TOKEN', 'token-ficticio')
    with TestClient(crear_app(recolector=lambda *a, **k: ([], [], {}))) as client:
        client.headers['X-Token'] = 'token-ficticio'
        yield client


def esperar(client, id):
    limite = monotonic() + 3
    while monotonic() < limite:
        r = client.get('/busquedas/' + id).json()
        if r['estado'] != 'en_curso':
            return r
        sleep(.005)
    pytest.fail('La búsqueda no terminó')


def test_salud_y_token(cliente, monkeypatch):
    cliente.headers.clear()
    assert cliente.get('/salud').json() == {'estado': 'ok'}
    for headers in ({}, {'X-Token': 'malo'}):
        assert cliente.post('/busquedas', json={'tema': 'IA'}, headers=headers).status_code == 401
        assert cliente.get('/busquedas/no-existe', headers=headers).status_code == 401


@pytest.mark.parametrize('token', [None, ''])
def test_servicio_abierto_sin_token(cliente, monkeypatch, token):
    if token is None:
        monkeypatch.delenv('RADAR_TOKEN')
    else:
        monkeypatch.setenv('RADAR_TOKEN', token)
    cliente.headers.clear()
    assert cliente.get('/salud').status_code == 200
    assert cliente.get('/busquedas/no-existe').status_code == 404
    assert cliente.get('/docs').status_code == 200
    assert '/busquedas' in cliente.get('/openapi.json').json()['paths']
    r = cliente.post('/busquedas', json={'tema': 'IA'})
    assert r.status_code == 202
    assert esperar(cliente, r.json()['id'])['estado'] == 'lista'


def test_resultado_contrato(monkeypatch):
    monkeypatch.setenv('RADAR_TOKEN', 'token-ficticio')
    fixture = Path(__file__).parent / 'fixtures'
    def pedir(recurso, parametros):
        archivo = 'youtube_search.json' if recurso == 'search' else 'youtube_videos.json'
        return json.loads((fixture / archivo).read_text(encoding='utf-8'))
    monkeypatch.setenv('YOUTUBE_API_KEY', 'ficticia')
    monkeypatch.setenv('AUTOR_HASH_SAL', 'sal-ficticia')
    ps, ms = buscar_con_metricas('IA', 'MX', 'es', datetime(2026, 1, 1,
        tzinfo=timezone.utc), peticion=pedir)
    llamadas = []
    def recolector(tema, **kwargs):
        llamadas.append((tema, kwargs))
        return ps, ms, {'youtube': {'publicaciones': len(ps)}}
    with TestClient(crear_app(recolector=recolector)) as client:
        client.headers['X-Token'] = 'token-ficticio'
        r = client.post('/busquedas', json={'tema': 'IA'})
        assert r.status_code == 202
        assert r.json()['estado'] == 'en_curso'
        resultado = esperar(client, r.json()['id'])
        assert resultado['estado'] == 'lista'
        assert resultado['publicaciones'] == [p.model_dump(mode='json') for p in ps]
        assert resultado['metricas'] == [m.model_dump(mode='json') for m in ms]
        assert llamadas == [('IA', dict(dias=7, redes=['youtube', 'linkedin', 'tiktok'],
                                      paises=['MX', 'CO', 'AR', 'CL', 'PE']))]


def test_ocupada_y_error(monkeypatch):
    monkeypatch.setenv('RADAR_TOKEN', 'token-ficticio')
    liberar = Event()
    def falla(*a, **k):
        liberar.wait(3)
        raise ValueError('secreto-ficticio y cuerpo del proveedor')
    with TestClient(crear_app(recolector=falla)) as client:
        client.headers['X-Token'] = 'token-ficticio'
        try:
            r = client.post('/busquedas', json={'tema': 'IA'}).json()
            assert client.get('/busquedas/' + r['id']).json()['estado'] == 'en_curso'
            assert client.post('/busquedas', json={'tema': 'otro'}).status_code == 409
        finally:
            liberar.set()
        resultado = esperar(client, r['id'])
        assert resultado['estado'] == 'error'
        assert resultado['resumen'] == {}
        assert 'secreto' not in str(resultado)
        assert 'proveedor' not in str(resultado)
        assert client.post('/busquedas', json={'tema': 'IA'}).status_code == 202


@pytest.mark.parametrize('cuerpo', [{}, {'tema': ''}, {'tema': '  '}, {'tema': ', ,'},
    {'tema': 'a,b,c,d,e,f'}, {'tema': '#'}, {'tema': 'IA', 'redes': []},
    {'tema': 'IA', 'redes': ['otra']}, {'tema': 'IA', 'dias': 0},
    {'tema': 'IA', 'dias': 36501}, {'tema': 'IA', 'dias': 1.5},
    {'tema': 'IA', 'dias': True}, {'tema': 'IA', 'paises': []},
    {'tema': 'IA', 'paises': ['MEX']}])
def test_validacion(cliente, cuerpo):
    assert cliente.post('/busquedas', json=cuerpo).status_code == 422


def test_limite_memoria(cliente):
    ids = []
    for _ in range(21):
        r = cliente.post('/busquedas', json={'tema': 'IA'}).json()
        ids.append(r['id'])
        assert esperar(cliente, r['id'])['estado'] == 'lista'
    assert cliente.get('/busquedas/' + ids[0]).status_code == 404
    assert all(cliente.get('/busquedas/' + id).status_code == 200 for id in ids[1:])


def test_parametros_normalizados(monkeypatch):
    monkeypatch.setenv('RADAR_TOKEN', 'token-ficticio')
    llamadas = []
    def recolector(tema, **kwargs):
        llamadas.append((tema, kwargs))
        return [], [], {}
    with TestClient(crear_app(recolector=recolector)) as client:
        client.headers['X-Token'] = 'token-ficticio'
        r = client.post('/busquedas', json={'tema': '#IA, educación', 'dias': 36500,
            'redes': ['tiktok', 'tiktok'], 'paises': [' co ', 'CO', 'mx']})
        assert r.status_code == 202
        esperar(client, r.json()['id'])
    assert llamadas == [('#IA, educación', dict(dias=36500, redes=['tiktok'], paises=['CO', 'MX']))]


def test_semillas_entorno(monkeypatch, tmp_path):
    ruta = tmp_path / 'semillas.txt'
    ruta.write_text('MS4wLjABarchivo\n', encoding='utf-8')
    monkeypatch.setenv('TIKTOK_CUENTAS', ' MS4wLjABentorno,MS4wLjABotra, MS4wLjABentorno ')
    assert tiktok_cuentas.leer_semillas(ruta) == ['MS4wLjABentorno', 'MS4wLjABotra']
    monkeypatch.setenv('TIKTOK_CUENTAS', 'https://tiktok.com/@ejemplo')
    with pytest.raises(ValueError):
        tiktok_cuentas.leer_semillas(ruta)
    monkeypatch.setenv('TIKTOK_CUENTAS', '')
    assert tiktok_cuentas.leer_semillas(ruta) == []
    monkeypatch.delenv('TIKTOK_CUENTAS')
    assert tiktok_cuentas.leer_semillas(ruta) == ['MS4wLjABarchivo']
