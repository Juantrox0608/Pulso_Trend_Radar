import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.error import HTTPError

import pytest

from radar.recoleccion.presupuesto_busqueda import PresupuestoBusqueda, LimiteBusqueda
from radar.recoleccion import linkedin_buscar as buscar

AHORA=datetime(2026,10,17,12,tzinfo=timezone.utc)


def presupuesto(tmp_path,**kw):
    return PresupuestoBusqueda(tmp_path/'gasto.json',reloj=lambda:AHORA,**kw)


def respuesta(costo='0.007'):
    return {'usage':{'cost':costo},'choices':[{'message':{'annotations':[]}}]}


def test_reserva_antes_y_liquida_costo_real(tmp_path):
    p=presupuesto(tmp_path)
    def pedir(_):
        assert json.loads((tmp_path/'gasto.json').read_text())['usado_usd']=='0.05'
        return respuesta()
    assert p.llamar(None,pedir)==respuesta()
    datos=json.loads((tmp_path/'gasto.json').read_text())
    assert Decimal(datos['usado_usd'])==Decimal('0.007')
    assert set(datos)=={'dia','usado_usd'}


def test_limite_diario_se_conserva_entre_procesos(tmp_path):
    p=presupuesto(tmp_path,diario='0.05')
    p.llamar(None,lambda _:respuesta())
    otro=presupuesto(tmp_path,diario='0.05')
    with pytest.raises(LimiteBusqueda):
        otro.llamar(None,lambda _:pytest.fail('No debe gastar'))
    otro.reloj=lambda:AHORA+timedelta(days=1)
    assert otro.llamar(None,lambda _:respuesta())==respuesta()


def test_tope_por_corrida(tmp_path):
    p=presupuesto(tmp_path,maximo=2)
    for _ in range(2): p.llamar(None,lambda _:respuesta())
    with pytest.raises(LimiteBusqueda,match='corrida'):
        p.llamar(None,lambda _:pytest.fail('No debe gastar'))


@pytest.mark.parametrize('codigo',[402,429])
def test_saldo_o_cuota_corta_sin_reintentar(tmp_path,codigo):
    p=presupuesto(tmp_path); llamadas=[]
    def pedir(_):
        llamadas.append(1)
        raise HTTPError('privado',codigo,'clave_secreta',{},None)
    with pytest.raises(LimiteBusqueda) as exc: p.llamar(None,pedir)
    with pytest.raises(LimiteBusqueda): p.llamar(None,pedir)
    assert llamadas==[1] and 'clave_secreta' not in str(exc.value)
    assert Decimal(json.loads((tmp_path/'gasto.json').read_text())['usado_usd'])==Decimal('0.05')


@pytest.mark.parametrize('retorno',[{}, {'usage':{'cost':'NaN'}}, {'usage':{'cost':-1}}])
def test_costo_desconocido_no_se_cuenta_como_cero(tmp_path,retorno):
    p=presupuesto(tmp_path)
    with pytest.raises(ValueError): p.llamar(None,lambda _:retorno)
    assert Decimal(json.loads((tmp_path/'gasto.json').read_text())['usado_usd'])==Decimal('0.05')


def test_timeout_conserva_reserva(tmp_path):
    def pedir(_): raise TimeoutError('clave_secreta')
    with pytest.raises(ValueError) as exc: presupuesto(tmp_path).llamar(None,pedir)
    assert 'clave_secreta' not in str(exc.value)
    assert Decimal(json.loads((tmp_path/'gasto.json').read_text())['usado_usd'])==Decimal('0.05')


def test_archivo_roto_o_en_uso_no_permite_gasto(tmp_path):
    p=presupuesto(tmp_path)
    p.ruta.write_text('roto')
    with pytest.raises(ValueError): p.llamar(None,lambda _:pytest.fail('No gastar'))
    p.ruta.unlink()
    p.ruta.with_suffix('.lock').write_text('ocupado')
    with pytest.raises(LimiteBusqueda): p.llamar(None,lambda _:pytest.fail('No gastar'))


def test_transporte_real_del_modulo_aplica_control(tmp_path,monkeypatch):
    monkeypatch.setattr(buscar,'_presupuesto',presupuesto(tmp_path,maximo=1))
    llamadas=[]
    def pedir(req):
        llamadas.append(req)
        return respuesta()
    monkeypatch.setattr(buscar,'_pedir',pedir)
    assert buscar.buscar_urls('IA',clave='ficticia')[0]==[]
    with pytest.raises(LimiteBusqueda): buscar.buscar_urls('otra',clave='ficticia')
    assert len(llamadas)==1


def test_tope_conserva_posts_reunidos(tmp_path,monkeypatch):
    from pathlib import Path
    url='https://www.linkedin.com/posts/autorficticio_ia-activity-2234567890123456789-abcd'
    html=(Path(__file__).parent/'fixtures/linkedin_post.html').read_text(encoding='utf-8')
    monkeypatch.setattr(buscar,'_presupuesto',presupuesto(tmp_path,maximo=1))
    def pedir(_):
        datos=respuesta()
        datos['choices'][0]['message']['annotations']=[{'url_citation':{'url':url}}]
        return datos
    monkeypatch.setattr(buscar,'_pedir',pedir)
    ps,ms,r=buscar.descubrir(['IA','agentes'],clave='ficticia',sal='sal',obtener=lambda _: (url,html))
    assert len(ps)==len(ms)==1
    assert r['aviso'] and r['costo_usd']==Decimal('0.007')


def test_tiktok_y_linkedin_comparten_el_tope(tmp_path,monkeypatch):
    from radar.recoleccion import tiktok_cuentas
    monkeypatch.setattr(buscar,'_presupuesto',presupuesto(tmp_path,maximo=1))
    llamadas=[]
    def pedir(req):
        llamadas.append(req)
        return respuesta()
    monkeypatch.setattr(buscar,'_pedir',pedir)
    buscar.buscar_urls('IA',clave='ficticia')
    with pytest.raises(LimiteBusqueda):
        tiktok_cuentas.descubrir_cuentas(['IA'],clave='ficticia',
            extractor=lambda _:pytest.fail('No extraer'))
    assert len(llamadas)==1


def test_costo_mayor_que_reserva_se_registra_y_frena_la_siguiente(tmp_path):
    p=presupuesto(tmp_path)
    p.llamar(None,lambda _:respuesta('0.30'))
    assert Decimal(json.loads(p.ruta.read_text())['usado_usd'])==Decimal('0.30')
    with pytest.raises(LimiteBusqueda): p.llamar(None,lambda _:pytest.fail('No debe gastar'))
