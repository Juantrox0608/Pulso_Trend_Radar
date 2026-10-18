import json
from decimal import Decimal
from urllib.error import HTTPError

import pytest

from radar.recoleccion import linkedin_buscar as lb, tiktok_cuentas as tc, buscar
from radar.recoleccion.presupuesto_busqueda import PresupuestoBusqueda
from test_linkedin_buscar import URL, url, respuesta, pagina
from test_tiktok_cuentas import entrada, AHORA, CANAL


@pytest.fixture(autouse=True)
def sin_red(monkeypatch, tmp_path):
    monkeypatch.setenv('GROQ_API_KEY', 'groq_ficticia')
    monkeypatch.setattr(lb, '_presupuesto', PresupuestoBusqueda(tmp_path/'gasto.json'))
    def prohibido(*a, **k):
        pytest.fail('Red prohibida')
    monkeypatch.setattr('socket.socket.connect', prohibido)
    monkeypatch.setattr('socket.create_connection', prohibido)


def groq(texto='', tools=None):
    return {'choices': [{'message': {'content': texto, 'executed_tools': tools or []}}],
            'usage': {'total_tokens': 123, 'cost': 99}}


@pytest.mark.parametrize('fallo', [402, 429, 500, 'timeout', 'invalida'])
def test_busqueda_respaldo_y_urls_de_herramientas(fallo):
    pedidos, resumen = [], {}
    def pedir(req):
        pedidos.append(req)
        if 'openrouter.ai' in req.full_url:
            if fallo == 'timeout':
                raise TimeoutError('groq_ficticia privada')
            if fallo == 'invalida':
                return {}
            raise HTTPError('privado', fallo, 'groq_ficticia', {}, None)
        return groq(url(1)+',\nhttps://malicioso.test/post',
                    [{'search_results': {'results': [{'url': URL+'.'}, {'url': url(0)}]}}])
    urls, costo = lb.buscar_urls('IA educación', clave='or_ficticia', pedir=pedir, resumen=resumen)
    assert urls == [URL, url(1)] and costo == Decimal('0')
    assert resumen == {'proveedor': 'groq', 'groq_tokens': 123}
    req = pedidos[1]
    assert req.get_header('User-agent') and 'Python-urllib' not in req.get_header('User-agent')
    assert req.get_header('Authorization') == 'Bearer groq_ficticia'
    cuerpo = json.loads(req.data)
    assert cuerpo['tools'] == [{'type': 'browser_search'}]
    assert cuerpo['tool_choice'] == 'required' and cuerpo['reasoning_effort'] == 'low'
    assert cuerpo['model'] == 'openai/gpt-oss-20b' and cuerpo['max_completion_tokens'] == 2000
    assert 'linkedin.com' in cuerpo['messages'][0]['content']
    assert 'IA educación' in cuerpo['messages'][0]['content']


def test_openrouter_sigue_principal():
    reqs, resumen = [], {}
    def pedir(req):
        reqs.append(req)
        return respuesta([URL])
    assert lb.buscar_urls('IA', clave='or_ficticia', pedir=pedir, resumen=resumen) == ([URL], Decimal('.007'))
    assert len(reqs) == 1 and resumen['proveedor'] == 'openrouter'


def test_sin_groq_conserva_error_actual(monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY')
    reqs = []
    def pedir(req):
        reqs.append(req)
        raise TimeoutError('or_ficticia')
    with pytest.raises(ValueError, match='OpenRouter') as exc:
        lb.buscar_urls('IA', clave='or_ficticia', pedir=pedir)
    assert len(reqs) == 1 and 'or_ficticia' not in str(exc.value)


@pytest.mark.parametrize('retorno', [None, {}, {'choices': []}])
def test_ambos_fallan_sin_filtrar_secretos(retorno):
    def pedir(req):
        if retorno is None:
            raise ValueError('or_ficticia groq_ficticia nombre_privado')
        return retorno
    with pytest.raises(ValueError) as exc:
        lb.buscar_urls('IA', clave='or_ficticia', pedir=pedir)
    assert all(s not in str(exc.value) for s in ('or_ficticia', 'groq_ficticia', 'nombre_privado'))


def test_solo_groq_y_resumen_linkedin():
    ps, ms, r = lb.descubrir(['IA', 'educación'], clave='', sal='sal',
        pedir=lambda req: groq(URL), obtener=lambda u: (u, pagina()), pausa=lambda _: None)
    assert len(ps) == len(ms) == 1 and r['costo_usd'] == 0 and r['groq_tokens'] == 246
    assert [p['proveedor'] for p in r['proveedores']] == ['groq', 'groq']


def test_presupuesto_sigue_aplicando_con_respaldo(monkeypatch, tmp_path):
    p = PresupuestoBusqueda(tmp_path/'gasto.json', maximo=1)
    monkeypatch.setattr(lb, '_presupuesto', p)
    reqs = []
    def pedir(req):
        reqs.append(req)
        return respuesta([]) if 'openrouter.ai' in req.full_url else groq(URL)
    monkeypatch.setattr(lb, '_pedir', pedir)
    lb.buscar_urls('IA', clave='ficticia')
    assert lb.buscar_urls('educación', clave='ficticia')[0] == [URL]
    assert len(reqs) == 2 and p.intentos == 1


def test_semillas_tiktok_usan_dominio_y_resumen():
    video = 'https://www.tiktok.com/@ficticio/video/'+entrada()['id']
    def pedir(req):
        assert 'tiktok.com' in json.loads(req.data)['messages'][0]['content']
        return groq(tools=[{'output': json.dumps({'url': video+','})}])
    cuentas, r = tc.descubrir_cuentas(['IA'], clave='', pedir=pedir,
        extractor=lambda _: entrada(), pausa=lambda _: None)
    assert cuentas == [CANAL] and r['groq_tokens'] == 123 and r['costo_usd'] == 0
    assert r['proveedores'][0]['proveedor'] == 'groq'


@pytest.mark.parametrize('fallo', ['429', 'cuota', 'invalida', 'timeout', 'sin_clave'])
def test_filtro_respaldo_mismo_prompt_y_parametros(fallo):
    reqs = []
    def pedir(req):
        reqs.append(req)
        if 'openrouter.ai' in req.full_url:
            if fallo == '429':
                raise HTTPError('privada', 429, 'groq_ficticia', {}, None)
            if fallo == 'timeout':
                raise TimeoutError('groq_ficticia')
            return {'choices': []}
        return groq('1: SI\n2: NO')
    filtro = tc.FiltroTema('IA educación', clave='' if fallo == 'sin_clave' else 'ficticia',
                           pedir=pedir, pausa=lambda _: None, reloj=lambda: AHORA)
    if fallo == 'cuota':
        filtro.dia, filtro.usados = AHORA.date().isoformat(), 50
    pares = [tc.tiktok.convertir_entrada(entrada(sufijo=i), sal='sal', ahora=AHORA) for i in range(2)]
    filtrados, r = filtro.filtrar(pares)
    assert filtrados == pares[:1] and r['lotes_sin_filtrar'] == 0
    assert r['lotes_groq'] == 1 and r['lotes_openrouter'] == 0
    req = reqs[-1]
    assert req.get_header('User-agent')
    cuerpo = json.loads(req.data)
    assert cuerpo['max_completion_tokens'] == 6000 and cuerpo['temperature'] == 0
    assert cuerpo['reasoning_effort'] == 'low' and 'tools' not in cuerpo
    if len(reqs) > 1:
        assert cuerpo['messages'] == json.loads(reqs[0].data)['messages']
    assert all(s not in cuerpo['messages'][0]['content'] for s in ('usuario_ficticio', 'https://', CANAL))


def test_filtro_ambos_fallan_conserva_lote():
    def pedir(req):
        raise ValueError('or_ficticia groq_ficticia nombre_privado')
    filtro = tc.FiltroTema('IA', clave='or_ficticia', pedir=pedir, pausa=lambda _: None)
    pares = [tc.tiktok.convertir_entrada(entrada(), sal='sal', ahora=AHORA)]
    filtrados, r = filtro.filtrar(pares)
    assert filtrados == pares and r['lotes_sin_filtrar'] == 1
    assert r['lotes_groq'] == r['lotes_openrouter'] == 0
    assert all(s not in str(r) for s in ('or_ficticia', 'groq_ficticia', 'nombre_privado'))


def test_captura_propaga_contadores_de_proveedores():
    filtro = tc.FiltroTema('IA', clave='', pedir=lambda req: groq('1: SI'), pausa=lambda _: None)
    _, _, r = tc.capturar([CANAL], sal='sal', ahora=AHORA, listar=lambda c,n: [entrada()], filtro=filtro)
    assert r['lotes_groq'] == 1 and r['lotes_openrouter'] == 0


def test_busqueda_general_agrega_proveedores_y_tokens():
    def recolector(tema, dias):
        return [], [], {'consultas': 1, 'costo_usd': Decimal('.01'), 'groq_tokens': 123,
                        'proveedores': [{'consulta': 1, 'proveedor': 'groq'}]}
    _, _, r = buscar.recolectar('IA, educación', redes=['linkedin'], recolectores={'linkedin': recolector})
    assert r['linkedin']['detalle']['groq_tokens'] == 246
    assert len(r['linkedin']['detalle']['proveedores']) == 2
    assert [p['consulta'] for p in r['linkedin']['detalle']['proveedores']] == [1, 2]


def test_costo_conocido_openrouter_se_conserva_si_responde_groq():
    def pedir(req):
        if 'openrouter.ai' in req.full_url:
            return {'usage': {'cost': '0.007'}, 'choices': [{'message': {'annotations': 'invalido'}}]}
        return groq(URL)
    urls, costo = lb.buscar_urls('IA', clave='ficticia', pedir=pedir)
    assert urls == [URL] and costo == Decimal('0.007')


def test_cuota_groq_corta_el_filtro_en_lotes_siguientes():
    llamadas=[]
    def pedir(req):
        llamadas.append(req)
        raise HTTPError('privada',429,'groq_ficticia',{},None)
    par=tc.tiktok.convertir_entrada(entrada(),sal='sal',ahora=AHORA)
    salida,r=tc.FiltroTema('IA',clave='',pedir=pedir,pausa=lambda _:None).filtrar([par]*61)
    assert len(salida)==61 and r['lotes_sin_filtrar']==3
    assert len(llamadas)==1 and 'groq_ficticia' not in str(r)


def test_costo_openrouter_valido_con_respuesta_invalida_no_se_pierde():
    def pedir(req):
        if 'openrouter.ai' in req.full_url:
            return {'usage': {'cost': '.012'}, 'choices': []}
        return groq(URL)
    assert lb.buscar_urls('IA', clave='ficticia', pedir=pedir) == ([URL], Decimal('.012'))


def test_groq_tambien_429_conserva_lote_y_error_seguro():
    def pedir(req):
        raise HTTPError('url_privada', 429, 'groq_ficticia or_ficticia', {}, None)
    filtro = tc.FiltroTema('IA', clave='or_ficticia', pedir=pedir, pausa=lambda _: None)
    pares = [tc.tiktok.convertir_entrada(entrada(), sal='sal', ahora=AHORA)]
    salida, r = filtro.filtrar(pares)
    assert salida == pares and r['lotes_sin_filtrar'] == 1
    assert 'ficticia' not in str(r) and 'url_privada' not in str(r)


def test_filtro_openrouter_exitoso_no_llama_groq():
    reqs = []
    def pedir(req):
        reqs.append(req)
        return groq('1: SI')
    filtro = tc.FiltroTema('IA', clave='ficticia', pedir=pedir, pausa=lambda _: None)
    pares = [tc.tiktok.convertir_entrada(entrada(), sal='sal', ahora=AHORA)]
    assert filtro.filtrar(pares)[1]['lotes_openrouter'] == 1
    assert len(reqs) == 1 and 'openrouter.ai' in reqs[0].full_url


@pytest.mark.parametrize('codigo', [402, 429])
def test_error_de_saldo_conserva_reserva_y_usa_groq(monkeypatch, tmp_path, codigo):
    p = PresupuestoBusqueda(tmp_path/'gasto.json')
    monkeypatch.setattr(lb, '_presupuesto', p)
    reqs = []
    def pedir(req):
        reqs.append(req)
        if 'openrouter.ai' in req.full_url:
            raise HTTPError('privado', codigo, 'groq_ficticia', {}, None)
        return groq(URL)
    monkeypatch.setattr(lb, '_pedir', pedir)
    for _ in range(2):
        assert lb.buscar_urls('IA', clave='ficticia') == ([URL], Decimal('0'))
    assert len(reqs) == 3 and p.intentos == 1
    assert Decimal(json.loads(p.ruta.read_text())['usado_usd']) == Decimal('.05')
