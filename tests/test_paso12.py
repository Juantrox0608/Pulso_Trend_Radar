from datetime import timedelta
from email.message import Message
import json
import re
import pytest
from urllib.error import HTTPError
from radar.recoleccion import tiktok_cuentas as tc
from test_tiktok_cuentas import AHORA, CANAL, entrada, respuesta

@pytest.fixture
def tiempo(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'groq_ficticia')
    class Tiempo:
        ahora = AHORA
        pausas = []
        def reloj(self): return self.ahora
        def pausa(self, segundos):
            self.pausas.append(segundos)
            self.ahora += timedelta(seconds=segundos)
    return Tiempo()

def pares(n=1):
    return [tc.tiktok.convertir_entrada(entrada(sufijo=i), sal='sal', ahora=AHORA) for i in range(n)]

def test_pausa_groq_entre_lotes_y_vueltas(tiempo):
    llamadas=[]
    def pedir(req):
        llamadas.append(tiempo.ahora)
        return respuesta('1: SI')
    filtro=tc.FiltroTema('IA', clave='', pedir=pedir, pausa=tiempo.pausa, reloj=tiempo.reloj)
    for _ in range(3): assert filtro.filtrar(pares())[1]['lotes_groq']==1
    assert llamadas == [AHORA, AHORA+timedelta(seconds=30), AHORA+timedelta(seconds=60)]
    assert tiempo.pausas == [30,30]


def test_groq_lotes_de_30_y_reloj_transcurrido(tiempo):
    llamadas = []
    def pedir(req):
        prompt = json.loads(req.data)['messages'][0]['content']
        n = len(re.findall(r'^\d+: ', prompt, flags=re.M))
        llamadas.append((n, tiempo.ahora))
        tiempo.ahora += timedelta(seconds=2)
        return respuesta('\n'.join(f'{i}: SI' for i in range(1, n+1)))
    filtro = tc.FiltroTema('IA', clave='', pedir=pedir,
                          pausa=tiempo.pausa, reloj=tiempo.reloj)
    ps, r = filtro.filtrar(pares(61))
    assert len(ps) == 61 and r['lotes_groq'] == 3
    assert [n for n, _ in llamadas] == [30, 30, 1]
    assert tiempo.pausas == [28, 28]

@pytest.mark.parametrize('valor,espera', [(None,30), ('7',7), ('120',60), ('invalido',30), ('-5',0),
    ('Sat, 17 Oct 2026 12:00:12 GMT',12)])
def test_429_reintento_exitoso_y_retry_after(tiempo,valor,espera):
    llamadas=[]
    def pedir(req):
        llamadas.append(tiempo.ahora)
        if len(llamadas)==1:
            headers=Message()
            if valor is not None: headers['Retry-After']=valor
            raise HTTPError('privada',429,'clave_privada',headers,None)
        return respuesta('1: SI')
    filtro=tc.FiltroTema('IA', clave='', pedir=pedir, pausa=tiempo.pausa, reloj=tiempo.reloj)
    ps,r=filtro.filtrar(pares())
    assert len(ps)==1 and r['lotes_groq']==1 and r['aviso'] is None
    assert tiempo.pausas==[espera] and len(llamadas)==2


def test_sin_proveedores_descarta_todos_los_lotes():
    ps,r=tc.FiltroTema('IA',clave='',pedir=lambda _:pytest.fail('No pedir')).filtrar(pares(61))
    assert ps==[] and r['lotes_descartados_sin_filtro']==3
    assert r['aviso']=='3 lotes descartados: no se pudieron filtrar con el tema'


def test_hashtag_mixto_sin_proveedores_conserva_solo_coincidentes():
    directo, pendiente = pares(2)
    pendiente = (pendiente[0].model_copy(update={'hashtags': ('otro',)}), pendiente[1])
    ps, r = tc.FiltroTema('#IA, educación', clave='',
        pedir=lambda _:pytest.fail('No pedir')).filtrar([directo, pendiente])
    assert ps == [directo] and r['lotes_descartados_sin_filtro'] == 1


def test_groq_respuesta_invalida_reintenta(tiempo):
    respuestas=iter(['', '1: SI'])
    ps,r=tc.FiltroTema('IA',clave='',pedir=lambda _:respuesta(next(respuestas)),
        pausa=tiempo.pausa,reloj=tiempo.reloj).filtrar(pares())
    assert len(ps)==1 and r['lotes_groq']==1 and tiempo.pausas==[30]


def test_429_repetido_propaga_descarte_y_aviso(tiempo,capsys):
    llamadas=[]
    def pedir(req):
        llamadas.append(req)
        raise HTTPError('privada',429,'clave_privada',{},None)
    filtro=tc.FiltroTema('IA',clave='',pedir=pedir,pausa=tiempo.pausa,reloj=tiempo.reloj)
    ps,ms,r=tc.capturar([CANAL],sal='sal',ahora=AHORA,listar=lambda c,n:[entrada(sufijo=i) for i in range(30)],filtro=filtro)
    assert ps==ms==[] and r['lotes_descartados_sin_filtro']==1 and len(llamadas)==2
    tc._resumir(r)
    err=capsys.readouterr().err
    assert '1 lotes descartados: no se pudieron filtrar con el tema' in err
    assert 'privada' not in err


def test_retry_after_minusculas_y_siguiente_lote(tiempo):
    llamadas = []
    def pedir(req):
        llamadas.append(tiempo.ahora)
        if len(llamadas) == 1:
            raise HTTPError('privada', 429, 'clave_privada', {'retry-after': '8'}, None)
        return respuesta('1: SI')
    filtro = tc.FiltroTema('IA', clave='', pedir=pedir,
                          pausa=tiempo.pausa, reloj=tiempo.reloj)
    for _ in range(2):
        assert filtro.filtrar(pares())[1]['lotes_groq'] == 1
    assert tiempo.pausas == [8, 30]
    assert llamadas == [AHORA, AHORA+timedelta(seconds=8), AHORA+timedelta(seconds=38)]


def test_interrupcion_del_filtro_no_guarda_piezas_sin_filtrar():
    def pedir(req): raise KeyboardInterrupt
    filtro=tc.FiltroTema('IA',clave='ficticia',pedir=pedir)
    ps,ms,r=tc.capturar([CANAL],sal='sal',ahora=AHORA,listar=lambda c,n:[entrada()],filtro=filtro)
    assert ps==ms==[] and r['interrumpido'] and r['lotes_descartados_sin_filtro']==1
