import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError

import pytest
from radar.recoleccion import tiktok_cuentas as tc

AHORA = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
CANAL = 'canal_sintetico_123'

def entrada(dias=1, sufijo=0):
    fecha = AHORA - timedelta(days=dias)
    return dict(id=str((int(fecha.timestamp()) << 32) + sufijo), timestamp=fecha.timestamp(),
                description='IA para educación @mencion_ficticia #IA #NombreFicticio', duration=53,
                uploader_id='usuario_ficticio', uploader='NombreFicticio', channel_id=CANAL,
                view_count=1200, like_count=0, comment_count=None, repost_count=2)

@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def no(*a, **k): pytest.fail('Red prohibida')
    monkeypatch.setattr('socket.socket.connect', no)
    monkeypatch.setattr('socket.create_connection', no)


def test_plana_anonimiza_filtra_y_omite():
    buena, vieja, mala = entrada(), entrada(8), entrada(sufijo=1)
    mala.pop('timestamp')
    p, m, r = tc.videos_de_cuenta(CANAL, sal='sal', listar=lambda c, n: [buena, vieja, mala], ahora=AHORA)
    assert len(p) == len(m) == 1
    assert r == {'fuera_fecha': 1, 'omitidos': 1}
    assert m[0].likes == 0 and p[0].capturada_en == AHORA
    assert p[0].hashtags == ('ia',)
    salida = p[0].model_dump_json() + m[0].model_dump_json()
    for dato in (CANAL, 'usuario_ficticio', 'NombreFicticio', 'mencion_ficticia'):
        assert dato not in salida
    assert '@[usuario]' in salida

@pytest.mark.parametrize('errores,llamadas', [([True, False, True, True, False], 5), ([True]*5, 3)])
def test_cuentas_fallidas(errores, llamadas):
    intentos, pausas = [], []
    def listar(c, n):
        intentos.append(c)
        if errores[len(intentos)-1]: raise RuntimeError('usuario secreto')
        return [entrada()]
    p, m, r = tc.capturar([f'canal_00{i}' for i in range(5)], sal='sal', listar=listar, pausa=pausas.append, ahora=AHORA)
    assert len(intentos) == llamadas
    assert pausas == [3] * (llamadas-1)
    assert 'secreto' not in str(r)
    assert bool(r['aviso']) == (llamadas == 3)

@pytest.mark.parametrize('codigo', [403, 429])
def test_bloqueo_guarda_parcial(codigo):
    def listar(c, n):
        if c == 'canal_002': raise HTTPError('url_privada', codigo, 'usuario', {}, None)
        return [entrada()]
    p, m, r = tc.capturar(['canal_001', 'canal_002', 'canal_003'], sal='sal', listar=listar, pausa=lambda _:None, ahora=AHORA)
    assert len(p) == 1 and r['cuentas'] == 2 and r['aviso']


def respuesta(texto): return {'choices':[{'message':{'content':texto}}]}

@pytest.mark.parametrize('textos,conservados,sin_filtrar', [(['1: SI\n2: NO'], 1, 0), (['', ''], 2, 1), (['1: SI', '1: SI'], 2, 1), (['incorrecto', '1: SÍ\n2: NO'], 1, 0)])
def test_filtro(textos, conservados, sin_filtrar):
    pedidos = []
    def pedir(req):
        cuerpo = json.loads(req.data)
        pedidos.append(cuerpo)
        return respuesta(textos.pop(0))
    pares = [tc.tiktok.convertir_entrada(entrada(sufijo=i), sal='sal', ahora=AHORA) for i in range(2)]
    filtro = tc.FiltroTema('IA', clave='ficticia', pedir=pedir, pausa=lambda _:None)
    filtrados, r = filtro.filtrar(pares)
    assert len(filtrados) == conservados and r['lotes_sin_filtrar'] == sin_filtrar
    for pedido in pedidos:
        assert pedido['model'] == 'nvidia/nemotron-3-super-120b-a12b:free'
        assert pedido['reasoning'] == {'enabled':False}
        prompt = pedido['messages'][0]['content']
        for dato in ('https://', CANAL, 'usuario_ficticio', 'mencion_ficticia'): assert dato not in prompt


def test_filtro_429_no_vuelve_a_pedir():
    intentos = []
    def pedir(req):
        intentos.append(req)
        raise HTTPError('privado', 429, 'clave', {}, None)
    filtro = tc.FiltroTema('IA', clave='ficticia', pedir=pedir, pausa=lambda _:None)
    par = tc.tiktok.convertir_entrada(entrada(), sal='sal', ahora=AHORA)
    pares, r = filtro.filtrar([par]*61)
    assert len(pares) == 61 and len(intentos) == 1
    assert r['lotes_sin_filtrar'] == 3 and r['aviso']


def test_semillas_csv_y_exa(tmp_path):
    e = entrada()
    url = f"https://www.tiktok.com/@ficticio/video/{e['id']}"
    csv = tmp_path/'manual.csv'
    csv.write_text('url;texto\n'+url+';hola\n'+url+';otra\nhttps://www.linkedin.com/posts/ficticio_activity-1234567890123456789;no\n', encoding='utf-8-sig')
    assert tc.urls_desde_csv(csv) == [url]
    reqs, pausas = [], []
    def pedir(req):
        reqs.append(json.loads(req.data))
        return {'choices':[{'message':{'annotations':[{'url_citation':{'url':url}}, {'url_citation':{'url':url}}]}}], 'usage':{'cost':0}}
    cuentas, r = tc.descubrir_cuentas(['IA'], clave='ficticia', pedir=pedir, extractor=lambda _:dict(e), pausa=pausas.append)
    assert cuentas == [CANAL]
    assert reqs[0]['plugins'][0]['include_domains'] == ['tiktok.com']
    archivo = tmp_path/'semillas.txt'
    assert tc.guardar_semillas(archivo, cuentas+cuentas) == 1
    assert tc.guardar_semillas(archivo, cuentas) == 0
    assert tc.leer_semillas(archivo) == cuentas


def test_dos_vueltas(tmp_path):
    tiempos = iter([AHORA, AHORA+timedelta(hours=1)])
    pausas = []
    def pausa(segundos):
        pausas.append(segundos)
        if len(pausas) == 2: raise KeyboardInterrupt
    tc.ejecutar(['canal_001'], sal='sal', salida_dir=tmp_path, cada_horas=1,
                reloj=lambda:next(tiempos), pausa=pausa, listar=lambda c,n:[entrada()])
    archivos = sorted(tmp_path.glob('tiktok_*.json'))
    assert len(archivos) == 2 and pausas == [3600,3600]
    capturas = [json.loads(a.read_text(encoding='utf-8'))['metricas'][0]['capturada_en'] for a in archivos]
    assert capturas[0] != capturas[1]


def test_cuota_persistente_y_dia_siguiente(tmp_path):
    contador=tmp_path/'cuota.json'
    contador.write_text(json.dumps({'dia':AHORA.date().isoformat(),'pedidos':49}),encoding='utf-8')
    pedidos=[]
    par=tc.tiktok.convertir_entrada(entrada(),sal='sal',ahora=AHORA)
    def pedir(req):
        pedidos.append(req)
        return respuesta('1: SI')
    filtro=tc.FiltroTema('IA',clave='ficticia',contador=contador,pedir=pedir,pausa=lambda _:None,reloj=lambda:AHORA)
    assert filtro.filtrar([par])[1]['lotes_sin_filtrar']==0
    otro=tc.FiltroTema('IA',clave='ficticia',contador=contador,pedir=pedir,pausa=lambda _:None,reloj=lambda:AHORA)
    assert otro.filtrar([par])[1]['lotes_sin_filtrar']==1 and len(pedidos)==1
    otro.reloj=lambda:AHORA+timedelta(days=1)
    assert otro.filtrar([par])[1]['lotes_sin_filtrar']==0 and len(pedidos)==2


def test_429_del_filtro_solo_detiene_esa_captura():
    pedidos=[]
    def pedir(req):
        pedidos.append(req)
        if len(pedidos)==1:
            raise HTTPError('privado',429,'clave',{},None)
        return respuesta('1: SI')
    filtro=tc.FiltroTema('IA',clave='ficticia',pedir=pedir,pausa=lambda _:None)
    for _ in range(2):
        tc.capturar([CANAL],sal='sal',ahora=AHORA,listar=lambda c,n:[entrada()],filtro=filtro)
    assert len(pedidos)==2


def test_csv_con_solo_columna_url(tmp_path):
    url=f"https://www.tiktok.com/@ficticio/video/{entrada()['id']}"
    ruta=tmp_path/'urls.csv';ruta.write_text('url\n'+url+'\n',encoding='utf-8')
    assert tc.urls_desde_csv(ruta)==[url]


def test_evitar_dos_capturas_simultaneas(tmp_path):
    (tmp_path/'.captura.lock').write_text('otro proceso',encoding='ascii')
    with pytest.raises(ValueError,match='otra captura'):
        tc.ejecutar([CANAL],sal='sal',salida_dir=tmp_path,
            listar=lambda *a:pytest.fail('No debe consultar'))


def test_escritura_fallida_no_deja_json_incompleto(tmp_path,monkeypatch):
    def escribir(*a):
        print('{')
        raise OSError('fallo sintético')
    monkeypatch.setattr(tc,'imprimir_json',escribir)
    with pytest.raises(OSError):
        tc.ejecutar([CANAL],sal='sal',salida_dir=tmp_path,reloj=lambda:AHORA,listar=lambda c,n:[entrada()])
    assert list(tmp_path.glob('tiktok_*.json'))==[]
    assert not (tmp_path/'.captura.lock').exists()


def test_topes_de_semillas_y_consultas():
    with pytest.raises(ValueError,match='20'):
        tc.descubrir_cuentas(['IA']*21,clave='ficticia',pedir=lambda _:pytest.fail('No debe consultar'))
    urls=[f"https://www.tiktok.com/@ficticio/video/{int(entrada()['id'])+i}" for i in range(60)]
    llamadas=[]
    def extractor(url):
        llamadas.append(url)
        return {'channel_id':f'cuenta_{len(llamadas):04d}'}
    cuentas,_=tc._cuentas_de_urls(urls,extractor=extractor,pausa=lambda _:None)
    assert len(cuentas)==len(llamadas)==50


def test_listado_plano_sin_descarga(monkeypatch):
    opciones=[]
    class YDL:
        def __init__(self,opts): opciones.append(opts)
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def extract_info(self,url,download):
            assert url=='tiktokuser:'+CANAL and download is False
            return {'entries':[entrada()]}
    monkeypatch.setattr(tc.yt_dlp,'YoutubeDL',YDL)
    assert len(tc._listar(CANAL,30))==1
    assert opciones[0]['extract_flat'] and opciones[0]['skip_download']
    assert opciones[0]['playlistend']==30 and opciones[0]['retries']==0
    assert not opciones[0].get('cookiefile')

@pytest.mark.parametrize('cantidad', [21, 22])
def test_tope_consultas_antes_de_red(cantidad):
    with pytest.raises(ValueError, match='20 consultas'):
        tc.descubrir_cuentas(['IA']*cantidad, clave='ficticia', pedir=lambda _:pytest.fail('No pedir'))


def test_tope_50_semillas_y_pausas():
    urls = [f"https://www.tiktok.com/@ficticio/video/{entrada(sufijo=i)['id']}" for i in range(60)]
    llamadas, pausas = [], []
    def extraer(url):
        llamadas.append(url)
        return dict(entrada(sufijo=len(llamadas)-1), channel_id=f'cuenta_00{len(llamadas)}')
    cuentas, r = tc._cuentas_de_urls(urls, extractor=extraer, pausa=pausas.append)
    assert len(cuentas) == len(llamadas) == 50 and pausas == [1.5]*49
    assert r['fallidas'] == 0


def test_topes_captura_y_duplicados():
    llamadas=[]
    def listar(c, n):
        llamadas.append((c,n))
        return [entrada(sufijo=i) for i in range(40)]
    ps, ms, r = tc.capturar(['cuenta_001', 'cuenta_002', 'cuenta_003'], sal='sal',
        por_cuenta=30, maximo=31, ahora=AHORA, listar=listar, pausa=lambda _:None)
    assert len(ps) == len(ms) == r['videos'] == 30
    assert len(set(p.id for p in ps)) == 30 and len(llamadas) == 3
    ps, ms, r = tc.capturar(['cuenta_001','cuenta_002'], sal='sal', maximo=2,
        ahora=AHORA, listar=listar, pausa=lambda _:None)
    assert len(ps) == len(ms) == r['videos'] == 2 and r['cuentas'] == 1


def test_listado_una_llamada_sin_descarga_ni_cookies(monkeypatch):
    opciones, llamadas = [], []
    class YDL:
        def __init__(self, opts): opciones.append(opts)
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def extract_info(self, url, download):
            llamadas.append((url,download))
            return {'entries':[entrada()]}
    monkeypatch.setattr(tc.yt_dlp,'YoutubeDL',YDL)
    ps, ms, r = tc.videos_de_cuenta(CANAL,sal='sal',ahora=AHORA)
    assert len(ps) == 1 and llamadas == [('tiktokuser:'+CANAL,False)]
    opts=opciones[0]
    assert opts['skip_download'] and opts['extract_flat'] and opts['playlistend'] == 30
    assert opts['retries'] == opts['extractor_retries'] == 0
    assert not any(k in opts for k in ('cookiefile','cookiesfrombrowser','username','password'))


def test_canal_error_no_expone():
    def extraer(_): raise RuntimeError('usuario_ficticio canal_secreto')
    with pytest.raises(ValueError) as exc:
        tc.canal_de(f"https://www.tiktok.com/@usuario_ficticio/video/{entrada()['id']}",extractor=extraer)
    assert str(exc.value) == 'TikTok: no se pudo identificar la cuenta pública'


@pytest.mark.parametrize('url', ['https://tiktok.com.evil/video/1234567890123456789',
    'https://eviltiktok.com/video/1234567890123456789',
    'http://tiktok.com/video/1234567890123456789',
    'https://usuario:clave@tiktok.com/video/1234567890123456789',
    'https://tiktok.com/@ficticio', 'https://tiktok.com:444/video/1234567890123456789'])
def test_urls_no_permitidas(url):
    with pytest.raises(ValueError): tc.canal_de(url,extractor=lambda _:pytest.fail('No extraer'))


def test_cuota_diaria_persistida_y_reinicio(tmp_path):
    contador=tmp_path/'contador.json'
    datos=[]
    def pedir(req):
        datos.append(req)
        return respuesta('1: SI')
    par=tc.tiktok.convertir_entrada(entrada(),sal='sal',ahora=AHORA)
    filtro=tc.FiltroTema('IA',clave='ficticia',pedir=pedir,contador=contador,reloj=lambda:AHORA,pausa=lambda _:None)
    for _ in range(50): assert filtro.filtrar([par])[1]['lotes_sin_filtrar'] == 0
    assert filtro.filtrar([par])[1]['lotes_sin_filtrar'] == 1 and len(datos) == 50
    nuevo=tc.FiltroTema('IA',clave='ficticia',pedir=pedir,contador=contador,reloj=lambda:AHORA,pausa=lambda _:None)
    assert nuevo.filtrar([par])[1]['lotes_sin_filtrar'] == 1 and len(datos) == 50
    nuevo.reloj=lambda:AHORA+timedelta(days=1)
    assert nuevo.filtrar([par])[1]['lotes_sin_filtrar'] == 0 and len(datos) == 51
    assert json.loads(contador.read_text())['pedidos'] == 1


def test_lotes_de_30_y_pausa_entre_pedidos(monkeypatch):
    pedidos, pausas=[],[]
    monkeypatch.setattr(tc,'monotonic',lambda:10)
    def pedir(req):
        prompt=json.loads(req.data)['messages'][0]['content']
        n=len(re.findall(r'^\d+: ',prompt,flags=re.M))
        pedidos.append(n)
        return respuesta('\n'.join(f'{i}: SI' for i in range(1,n+1)))
    par=tc.tiktok.convertir_entrada(entrada(),sal='sal',ahora=AHORA)
    filtro=tc.FiltroTema('IA',clave='ficticia',pedir=pedir,pausa=pausas.append)
    ps,r=filtro.filtrar([par]*61)
    assert len(ps) == 61 and pedidos == [30,30,1] and pausas == [3.1,3.1]


@pytest.mark.parametrize('texto', ['1: SI\n1: NO', '1: TAL VEZ', '0: SI', '1: SI\n2: NO\nexplicación'])
def test_respuestas_malformadas_conservan_lote(texto):
    par=tc.tiktok.convertir_entrada(entrada(),sal='sal',ahora=AHORA)
    llamadas=[]
    def pedir(req):
        llamadas.append(req)
        return respuesta(texto)
    filtrados,r=tc.FiltroTema('IA',clave='ficticia',pedir=pedir,pausa=lambda _:None).filtrar([par])
    assert filtrados == [par] and r['lotes_sin_filtrar'] == 1 and len(llamadas) == 2


def test_filtro_no_envia_urls_embebidas():
    info=entrada()
    info['description'] += ' https://example.test/@autor www.example.test/usuario'
    par=tc.tiktok.convertir_entrada(info,sal='sal',ahora=AHORA)
    def pedir(req):
        prompt=json.loads(req.data)['messages'][0]['content']
        assert 'example.test' not in prompt
        return respuesta('1: SI')
    assert tc.FiltroTema('IA',clave='ficticia',pedir=pedir).filtrar([par])[0] == [par]


def test_error_cuenta_en_periodico_guarda_y_detiene(tmp_path):
    llamadas=[]
    def listar(c,n):
        llamadas.append(c)
        if c != 'cuenta_001': raise RuntimeError('HTTP Error 403 usuario privado')
        return [entrada()]
    tc.ejecutar(['cuenta_001','cuenta_002'],sal='sal',salida_dir=tmp_path,cada_horas=1,
        listar=listar,reloj=lambda:AHORA,pausa=lambda _:None)
    archivos=list(tmp_path.glob('*.json'))
    assert len(archivos) == 1 and len(llamadas) == 2
    assert len(json.loads(archivos[0].read_text())['publicaciones']) == 1


def test_interrupcion_durante_captura_guarda(tmp_path):
    def listar(c,n):
        if c == 'cuenta_002': raise KeyboardInterrupt
        return [entrada()]
    tc.ejecutar(['cuenta_001','cuenta_002'],sal='sal',salida_dir=tmp_path,cada_horas=1,
        listar=listar,reloj=lambda:AHORA,pausa=lambda _:None)
    assert len(json.loads(next(tmp_path.glob('*.json')).read_text())['publicaciones']) == 1


@pytest.mark.parametrize('argumentos,mensaje', [(['semillas','--consulta','IA'],'OPENROUTER_API_KEY'),
    (['capturar'],'No hay cuentas semilla')])
def test_cli_errores_sin_red(tmp_path,monkeypatch,capsys,argumentos,mensaje):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('OPENROUTER_API_KEY',raising=False)
    with pytest.raises(SystemExit) as exc: tc.main(argumentos)
    assert exc.value.code == 1 and mensaje in capsys.readouterr().err


def test_captura_filtrada_quita_metricas_del_descartado():
    filtro=tc.FiltroTema('IA',clave='ficticia',pedir=lambda _:respuesta('1: SI\n2: NO'),pausa=lambda _:None)
    ps,ms,r=tc.capturar([CANAL],sal='sal',ahora=AHORA,
        listar=lambda c,n:[entrada(),entrada(sufijo=1)],filtro=filtro)
    assert len(ps)==len(ms)==1 and ms[0].publicacion_id==ps[0].id
    assert r['descartados_tema']==1 and r['videos']==1


def test_hash_identico_al_video_individual():
    info=entrada()
    url=f"https://www.tiktok.com/@ficticio/video/{info['id']}"
    individual,_=tc.tiktok.recolectar(url,sal='sal',extractor=lambda _:info)
    planos,_,_=tc.videos_de_cuenta(CANAL,sal='sal',ahora=AHORA,listar=lambda c,n:[info])
    assert planos[0].autor_hash==individual.autor_hash
    assert planos[0].texto==individual.texto and planos[0].url==individual.url


def test_cli_semillas_desde_csv_sin_duplicados(tmp_path,monkeypatch,capsys):
    monkeypatch.chdir(tmp_path)
    url=f"https://www.tiktok.com/@ficticio/video/{entrada()['id']}"
    ruta=tmp_path/'manual.csv';ruta.write_text('url\n'+url+'\n',encoding='utf-8')
    monkeypatch.setattr(tc.tiktok,'_extraer',lambda _:entrada())
    for _ in range(2): tc.main(['semillas','--desde-csv',str(ruta)])
    assert tc.leer_semillas()==[CANAL]
    assert CANAL not in capsys.readouterr().err
    monkeypatch.delenv('OPENROUTER_API_KEY',raising=False)
    with pytest.raises(SystemExit) as exc: tc.main(['capturar','--tema','IA'])
    assert exc.value.code==1 and 'OPENROUTER_API_KEY' in capsys.readouterr().err


def test_json_utf8_emoji_y_sin_sobrescribir(tmp_path):
    info=entrada();info['description']='Educación con IA 🤖 @ficticio'
    for _ in range(2):
        tc.ejecutar([CANAL],sal='sal',salida_dir=tmp_path,reloj=lambda:AHORA,listar=lambda c,n:[info])
    archivos=list(tmp_path.glob('*.json'))
    assert len(archivos)==2
    assert all(json.loads(p.read_text(encoding='utf-8'))['publicaciones'][0]['texto']=='Educación con IA 🤖 @[usuario]' for p in archivos)
