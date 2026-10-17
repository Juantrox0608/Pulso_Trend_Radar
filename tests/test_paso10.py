import json
from pathlib import Path
from decimal import Decimal

import pytest

from radar.recoleccion import buscar, tiktok, tiktok_cuentas as tc


@pytest.fixture
def par():
    info = json.loads(Path('tests/fixtures/tiktok_video.json').read_text(encoding='utf-8'))
    return tiktok.convertir_entrada(info, sal='ficticia')


def test_busqueda_terminos_y_paises_sin_duplicados(par):
    llamadas = []
    def recolector(red):
        def consultar(*args):
            llamadas.append((red, *args))
            return [par[0]], [par[1]]
        return consultar
    ps, ms, _ = buscar.recolectar(' #ciberseguridad, fraude, , FRAUDE, #ciberseguridad ',
        paises=['MX', 'CO'], recolectores={r: recolector(r) for r in buscar.REDES})
    assert ps == [par[0]] and ms == [par[1]]
    assert llamadas == [
        ('youtube', '#ciberseguridad', 7, 'MX'), ('youtube', '#ciberseguridad', 7, 'CO'),
        ('youtube', 'fraude', 7, 'MX'), ('youtube', 'fraude', 7, 'CO'),
        ('linkedin', '#ciberseguridad', 7), ('linkedin', 'fraude', 7),
        ('tiktok', ' #ciberseguridad, fraude, , FRAUDE, #ciberseguridad ', 7)]


@pytest.mark.parametrize('tema', [', ,', 'a,b,c,d,e,f'])
def test_temas_invalidos_antes_de_consultar(tema):
    with pytest.raises(ValueError, match='términos'):
        buscar.recolectar(tema, recolectores={r: lambda *a: pytest.fail('No consultar') for r in buscar.REDES})
    with pytest.raises(ValueError, match='términos'):
        tc.FiltroTema(tema, clave='ficticia')


@pytest.mark.parametrize('tema,fragmento', [
    (' ciberseguridad, hacking, , HACKING, fraude digital ', 'específicamente'),
    ('ciberseguridad e inteligencia artificial', 'si trata de ciberseguridad e inteligencia artificial,'),
])
def test_pedido_preciso_y_amplio(tema, fragmento, par):
    pedidos = []
    def pedir(req):
        cuerpo = json.loads(req.data)
        pedidos.append(cuerpo['messages'][0]['content'])
        assert cuerpo['reasoning'] == {'enabled': False}
        return {'choices': [{'message': {'content': '1: NO'}}]}
    ps, r = tc.FiltroTema(tema, clave='ficticia', pedir=pedir).filtrar([par])
    assert ps == [] and r['descartados_tema'] == 1
    assert len(pedidos) == 1 and fragmento in pedidos[0]
    if ',' in tema:
        assert all(t in pedidos[0] for t in ['ciberseguridad', 'hacking', 'fraude digital'])
        assert 'al menos uno' in pedidos[0] and 'HACKING' not in pedidos[0]


def test_cinco_terminos_validos(par):
    filtro = tc.FiltroTema('uno,dos,tres,cuatro,cinco,UNO', clave='ficticia',
        pedir=lambda _: {'choices': [{'message': {'content': '1: SI'}}]})
    assert filtro.filtrar([par])[0] == [par]


def test_hashtag_exacto_sin_modelo_ni_clave(par):
    p, m = par
    pares = [(p.model_copy(update={'id': f'tt:{1234567890123456789+i}', 'hashtags': tags}), m)
             for i, tags in enumerate([('CiberSegurídad',), ('ciberseguridadextra',), (), ('ciber_seguridad',)])]
    filtro = tc.FiltroTema('#CIBERSEGURIDAD', clave='',
        pedir=lambda _: pytest.fail('No debe llamar al modelo'))
    salida, r = filtro.filtrar(pares)
    assert salida == pares[:1] and r['descartados_tema'] == 3
    assert r['lotes_sin_filtrar'] == 0 and filtro.usados == 0


def test_hashtag_mixto_solo_envia_no_coincidentes_al_modelo(par):
    p, m = par
    directo = (p.model_copy(update={'hashtags': ('ciberseguridad',), 'texto': 'No enviar'}), m)
    pendiente = (p.model_copy(update={'id': 'tt:1234567890123456790', 'hashtags': (), 'texto': 'Fraude digital'}), m)
    def pedir(req):
        prompt = json.loads(req.data)['messages'][0]['content']
        assert 'Fraude digital' in prompt and 'No enviar' not in prompt
        assert '#ciberseguridad' not in prompt and 'específicamente' in prompt
        return {'choices': [{'message': {'content': '1: NO'}}]}
    salida, r = tc.FiltroTema('#ciberseguridad, fraude', clave='ficticia', pedir=pedir).filtrar([pendiente, directo])
    assert salida == [directo] and r['descartados_tema'] == 1


@pytest.mark.parametrize('descripcion,esperado', [
    ('\n\nDescripción @persona https://ejemplo.test\nSegunda', 'Descripción @[usuario]'),
    ('', 'Título @[usuario]'),
])
def test_titulo_descripcion_antes_de_title(descripcion, esperado):
    info = json.loads(Path('tests/fixtures/tiktok_video.json').read_text(encoding='utf-8'))
    info.update(description=descripcion, title='Título @persona www.ejemplo.test')
    p, _ = tiktok.convertir_entrada(info, sal='ficticia')
    assert p.titulo == esperado


def test_titulo_tiktok_limite_palabra(par):
    info = json.loads(Path('tests/fixtures/tiktok_video.json').read_text(encoding='utf-8'))
    info.update(description='palabra ' * 30, title='Cortado...')
    titulo = tiktok.convertir_entrada(info, sal='ficticia')[0].titulo
    assert len(titulo) <= 120 and titulo.endswith('palabra')


def test_resumen_linkedin_suma_consultas_y_costos_de_los_terminos():
    def consultar(*args):
        return [], [], {'consultas':1,'consultas_fallidas':0,'urls':2,'completados':2,
            'omitidos':0,'fuera_fecha':0,'costo_usd':Decimal('0.007'),'aviso':None}
    _,_,resumen=buscar.recolectar('ciberseguridad, fraude',redes=['linkedin'],
        recolectores={'linkedin':consultar})
    assert resumen['linkedin']['detalle']['consultas']==2
    assert resumen['linkedin']['detalle']['costo_usd']==Decimal('0.014')
