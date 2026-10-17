import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from radar.recoleccion import tiktok, linkedin, titulo_publico
from radar.recoleccion import youtube_metricas, buscar


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    monkeypatch.setattr('socket.socket.connect', lambda *a: pytest.fail('Red prohibida'))
    monkeypatch.setenv('YOUTUBE_API_KEY', 'ficticia')
    monkeypatch.setenv('AUTOR_HASH_SAL', 'ficticia')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'ficticia')


@pytest.fixture
def par():
    info = json.loads(Path('tests/fixtures/tiktok_video.json').read_text(encoding='utf-8'))
    return tiktok.convertir_entrada(info, sal='ficticia')


@pytest.mark.parametrize('preferido,texto,esperado', [
    ('Título @persona https://ejemplo.test', 'Otro', 'Título @[usuario]'),
    (' https://ejemplo.test ', '\n\nPrimera @persona www.ejemplo.test\nSegunda', 'Primera @[usuario]'),
    (None, ' \n https://ejemplo.test', None),
    ('Autor ideas', '', '[autor] ideas'),
])
def test_titulo_limpio(preferido, texto, esperado):
    assert titulo_publico(preferido, texto, 'Autor') == esperado


def test_limite_palabra():
    titulo = titulo_publico('palabra ' * 30, '')
    assert len(titulo) <= 120 and titulo.endswith('palabra')


def test_titulo_tiktok_y_respaldo():
    info = json.loads(Path('tests/fixtures/tiktok_video.json').read_text(encoding='utf-8'))
    info['title'] = 'Título de Nombre Ficticio @persona https://ejemplo.test'
    assert tiktok.convertir_entrada(info, sal='f')[0].titulo.startswith('Agentes IA')
    info['description'] = ''
    assert tiktok.convertir_entrada(info, sal='f')[0].titulo == 'Título de [autor] @[usuario]'
    info['title'] = ' '
    info['description'] = 'Descripción sin título preferido'
    assert tiktok.convertir_entrada(info, sal='f')[0].titulo == info['description']


@pytest.mark.parametrize('tipo', ['SocialMediaPosting', 'VideoObject'])
def test_headline_linkedin(tipo):
    url = 'https://www.linkedin.com/feed/update/urn:li:activity:2234567890123456789/'
    post = {'@type': tipo, 'headline': '<b>Idea</b> @persona https://ejemplo.test',
            'description': 'Descripción', 'author': {'name': 'Autor'}, 'datePublished': '2026-01-01T00:00:00Z'}
    html = '<script type="application/ld+json">' + json.dumps(post) + '</script>'
    assert linkedin.recolectar(url, sal='f', obtener=lambda _: (url, html))[0].titulo == 'Idea @[usuario]'


def test_recaptura_lotes_ausencias(tmp_path):
    ids = ['yt:' + f'video{i:06d}' for i in range(52)]
    a, b = tmp_path/'a.json', tmp_path/'b.json'
    a.write_text(json.dumps([{'id': i} for i in ids[:30]]), encoding='utf-8')
    b.write_text(json.dumps({'publicaciones': [{'id': i} for i in ids[29:]]}), encoding='utf-8')
    llamadas = []
    def pedir(recurso, parametros):
        llamadas.append(parametros)
        return {'items': [{'id': i, 'statistics': {'viewCount': '0'}}
                          for i in parametros['id'].split(',') if i != ids[-1][3:]]}
    ms, resumen = youtube_metricas.recapturar([a,b], peticion=pedir)
    assert len(ms) == 51 and resumen == dict(ids=52, llamadas=2, metricas=51, faltantes=1)
    assert len(llamadas[0]['id'].split(',')) == 50
    assert llamadas[0]['part'] == 'statistics'
    assert ms[0].vistas == 0 and ms[0].likes is None and ms[0].compartidos is None
    assert ms[0].origen == 'api_oficial'


def test_buscar_fallo_parcial_y_deduplicacion(par):
    p,m = par
    llamadas = []
    def yt(*args):
        llamadas.append(args)
        return [p], [m]
    def falla(*args):
        raise ValueError('secreto proveedor')
    ps, ms, r = buscar.recolectar('tema', recolectores={'youtube': yt, 'linkedin': falla,
        'tiktok': lambda *a: ([p],[m],{})})
    assert len(llamadas) == 5 and ps == [p] and ms == [m]
    assert r['linkedin']['fallidas'] == 1 and 'secreto' not in str(r)


def test_todas_fallan():
    def falla(*a): raise ValueError('privado')
    with pytest.raises(ValueError, match='Todas las redes'):
        buscar.recolectar('tema', recolectores=dict.fromkeys(('youtube','linkedin','tiktok'), falla))


def test_envio_lotes_y_fallo(par):
    p,m = par
    ps = [p.model_copy(update={'id': f'tt:{1234567890123456789+i}'}) for i in range(401)]
    ms = [m.model_copy(update={'publicacion_id': p.id}) for p in ps]
    cuerpos = []
    def pedir(request, *, timeout):
        assert timeout == 30 and request.full_url == 'http://localhost:8000/api/publicaciones'
        cuerpos.append(json.loads(request.data))
        if len(cuerpos) == 2: raise OSError('privado')
    assert buscar.enviar('http://localhost:8000', ps, ms, pedir=pedir) == [2]
    assert [len(c['publicaciones']) for c in cuerpos] == [200,200,1]
    assert all(len(c['metricas']) == len(c['publicaciones']) for c in cuerpos)


def test_cli_guarda_antes_de_envio_fallido(tmp_path, monkeypatch, par):
    p,m = par
    ruta = tmp_path/'salida.json'
    monkeypatch.setattr(buscar, 'recolectar', lambda *a, **kw: ([p],[m],{}))
    def enviar(*a):
        assert json.loads(ruta.read_text(encoding='utf-8'))['publicaciones'][0]['id'] == p.id
        return [1]
    monkeypatch.setattr(buscar, 'enviar', enviar)
    with pytest.raises(SystemExit) as exc:
        buscar.main(['--tema','tema','--salida',str(ruta),'--enviar','http://localhost'])
    assert exc.value.code == 1 and ruta.exists()


def test_cli_sin_enviar_no_post(monkeypatch, par, capsys):
    p,m = par
    monkeypatch.setattr(buscar, 'recolectar', lambda *a, **kw: ([p],[m],{}))
    monkeypatch.setattr(buscar, 'enviar', lambda *a: pytest.fail('POST no autorizado'))
    buscar.main(['--tema', 'tema'])
    assert json.loads(capsys.readouterr().out)['publicaciones'][0]['titulo'] == p.titulo


def test_recolectores_reales_delegan(monkeypatch, par):
    p,m = par
    llamadas = []
    def yt(tema, pais, idioma, desde):
        llamadas.append((tema,pais,idioma,desde))
        return [p],[m]
    def li(consultas, **kw):
        assert consultas == ['educación'] and kw['dias'] == 3
        assert kw['clave'] == kw['sal'] == 'ficticia'
        return [],[],{'aviso':None}
    class Filtro:
        def __init__(self, tema, **kw):
            assert tema == 'educación' and kw['clave'] == 'ficticia'
    def tt(cuentas, **kw):
        assert cuentas == ['canal_ficticio'] and isinstance(kw['filtro'], Filtro)
        assert kw['dias'] == 3 and kw['sal'] == 'ficticia'
        return [],[],{'aviso':None}
    monkeypatch.setattr(buscar.youtube, 'buscar_con_metricas', yt)
    monkeypatch.setattr(buscar.linkedin_buscar, 'descubrir', li)
    monkeypatch.setattr(buscar.tiktok_cuentas, 'leer_semillas', lambda: ['canal_ficticio'])
    monkeypatch.setattr(buscar.tiktok_cuentas, 'FiltroTema', Filtro)
    monkeypatch.setattr(buscar.tiktok_cuentas, 'capturar', tt)
    assert buscar.recolectar('educación', dias=3, paises=['mx','MX'])[0] == [p]
    assert len(llamadas) == 1 and llamadas[0][1:3] == ('MX','es')


@pytest.mark.parametrize('valor', ['-1', '1.5', True])
def test_recaptura_rechaza_contadores_invalidos(tmp_path, valor):
    ruta = tmp_path/'entrada.json'
    ruta.write_text('[{"id":"yt:vid_test01A"}]', encoding='utf-8')
    with pytest.raises(ValueError, match='estadísticas inválidas'):
        youtube_metricas.recapturar([ruta], peticion=lambda *a: {
            'items': [{'id':'vid_test01A', 'statistics':{'viewCount':valor}}]})


def test_recaptura_sin_contadores(tmp_path):
    ruta = tmp_path/'entrada.json'
    ruta.write_text('[{"id":"yt:vid_test01A"},{"id":"tt:1234567890123456789"}]', encoding='utf-8')
    ms, r = youtube_metricas.recapturar([ruta], peticion=lambda *a: {'items':[{'id':'vid_test01A'}]})
    assert ms == [] and r['faltantes'] == 0 and r['ids'] == 1


def test_recaptura_cli_utf8(tmp_path, monkeypatch):
    ruta = tmp_path/'salida.json'
    monkeypatch.setattr(youtube_metricas, 'recapturar', lambda *a: ([],dict(ids=0,llamadas=0,metricas=0,faltantes=0)))
    youtube_metricas.main(['entrada.json','--salida',str(ruta)])
    assert json.loads(ruta.read_text(encoding='utf-8')) == dict(publicaciones=[],metricas=[])


def test_post_real_configurado(monkeypatch):
    class Respuesta:
        status = 201
        def __enter__(self): return self
        def __exit__(self, *a): pass
    def abrir(request, *, timeout):
        assert request.method == 'POST' and timeout == 30
        return Respuesta()
    monkeypatch.setattr(buscar, 'urlopen', abrir)
    buscar._post(buscar.Request('http://localhost', data=b'{}', method='POST'), timeout=30)
