"""Captura periódica de cuentas semilla públicas de TikTok, sin sesión ni descarga."""
import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from math import isfinite
from io import StringIO
from itertools import islice
from pathlib import Path
from time import sleep, monotonic
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

import yt_dlp

from radar.contrato import Plataforma, id_desde_url
from radar.recoleccion import imprimir_json, texto_publico, terminos_tema, normalizar_hashtag, tiktok
from radar.recoleccion.linkedin_buscar import buscar_urls, _consultas, _entero, _pedir, _peticion_groq
from radar.recoleccion.presupuesto_busqueda import LimiteBusqueda

SEMILLAS = Path('data/raw/tiktok_cuentas.txt')


def _canal(valor):
    if not isinstance(valor, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,512}', valor):
        raise ValueError('TikTok: identificador de cuenta inválido')
    return valor


def _validar_video(url):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.username or p.password or p.port not in (None, 443)
            or not (p.hostname == 'tiktok.com' or (p.hostname or '').endswith('.tiktok.com'))
            or not re.fullmatch(r'/(?:@[^/]*/)?video/\d{15,22}/?', p.path)
            or id_desde_url(url)[0] != Plataforma.TIKTOK):
        raise ValueError('TikTok: enlace de video público inválido')


def canal_de(url, *, extractor=None):
    try:
        _validar_video(url)
        info = (extractor or tiktok._extraer)(url)
        if 'id' in info and str(info['id']) != id_desde_url(url)[1]:
            raise ValueError()
        return _canal(info['channel_id'])
    except Exception:
        raise ValueError('TikTok: no se pudo identificar la cuenta pública') from None


def _listar(channel_id, por_cuenta):
    with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'logger': tiktok._SinLog(),
            'skip_download': True, 'extract_flat': True, 'playlistend': por_cuenta,
            'socket_timeout': 20, 'retries': 0, 'extractor_retries': 0}) as ydl:
        info = ydl.extract_info('tiktokuser:' + channel_id, download=False)
        return list((info or {}).get('entries') or [])


class FalloTikTok(ValueError):
    def __init__(self, categoria, tipo):
        super().__init__('TikTok: no se pudo listar una cuenta pública')
        self.categoria, self.tipo = categoria, tipo


class BloqueoTikTok(FalloTikTok):
    pass


def _motivo_fallo(error):
    pendientes, vistos, motivos = [error], set(), set()
    while pendientes:
        actual = pendientes.pop()
        if not isinstance(actual, BaseException) or id(actual) in vistos:
            continue
        vistos.add(id(actual))
        texto = str(actual)
        codigo = getattr(actual, 'code', getattr(actual, 'status', None))
        match = re.search(r'(?i)(?:HTTP(?: Error)?[ :]+|status(?: code)?[ :]+)(\d{3})\b', texto)
        if match:
            codigo = int(match[1])
        if isinstance(codigo, int) and 400 <= codigo <= 599:
            motivos.add(f'http_{codigo}' if codigo in (403, 429) else 'http_otro')
        if isinstance(actual, TimeoutError) or re.search(r'(?i)\b(?:timed? out|timeout)\b', texto):
            motivos.add('tiempo_agotado')
        if isinstance(actual, yt_dlp.utils.ExtractorError) or re.search(
                r'(?i)\b(?:unable to extract|unsupported URL)\b', texto):
            motivos.add('extractor')
        pendientes.extend([actual.__cause__, actual.__context__, getattr(actual, 'cause', None),
                           getattr(actual, 'reason', None)])
        info = getattr(actual, 'exc_info', None)
        if isinstance(info, tuple) and len(info) > 1:
            pendientes.append(info[1])
    return next((m for m in ('http_403', 'http_429', 'http_otro', 'tiempo_agotado', 'extractor')
                 if m in motivos), 'otro')


def videos_de_cuenta(channel_id, *, sal, dias=7, por_cuenta=30, listar=None, ahora=None):
    _canal(channel_id)
    _entero(dias, 1, 36500, 'dias')
    _entero(por_cuenta, 1, 300, 'por_cuenta')
    ahora = ahora or datetime.now(timezone.utc)
    desde = ahora - timedelta(days=dias)
    publicaciones, metricas = [], []
    resumen = {'fuera_fecha': 0, 'omitidos': 0}
    try:
        entradas = list(islice(iter((listar or _listar)(channel_id, por_cuenta) or []), por_cuenta))
    except Exception as error:
        motivo = _motivo_fallo(error)
        clase = BloqueoTikTok if motivo in ('http_403', 'http_429') else FalloTikTok
        raise clase(motivo, type(error).__name__) from None
    if not entradas:
        raise FalloTikTok('sin_datos', 'FalloTikTok')
    for entrada in entradas:
        try:
            nativo = str(entrada['id'])
            fecha = datetime.fromtimestamp(int(nativo) >> 32, timezone.utc)
            if fecha < desde:
                resumen['fuera_fecha'] += 1
                continue
            p, m = tiktok.convertir_entrada(entrada, sal=sal, ahora=ahora)
            if p.publicada_en < desde:
                resumen['fuera_fecha'] += 1
                continue
        except Exception:
            resumen['omitidos'] += 1
            continue
        publicaciones.append(p)
        if m is not None:
            metricas.append(m)
    if not publicaciones and resumen['omitidos'] and not resumen['fuera_fecha']:
        raise FalloTikTok('sin_datos', 'FalloTikTok')
    return publicaciones, metricas, resumen


def urls_desde_csv(ruta):
    try:
        contenido = Path(ruta).read_bytes()
        try:
            texto = contenido.decode('utf-8-sig')
        except UnicodeDecodeError:
            texto = contenido.decode('cp1252')
        encabezado = texto.splitlines()[0] if texto else ''
        separador = ',' if encabezado.strip() == 'url' else csv.Sniffer().sniff(encabezado, delimiters=',;').delimiter
        lector = csv.DictReader(StringIO(texto), delimiter=separador)
        if 'url' not in (lector.fieldnames or []):
            raise ValueError()
        urls = []
        vistos = set()
        for fila in lector:
            url = (fila.get('url') or '').strip()
            try:
                _validar_video(url)
                identificador = id_desde_url(url)[1]
            except ValueError:
                continue
            if identificador not in vistos:
                vistos.add(identificador)
                urls.append(url)
        return urls
    except (OSError, UnicodeError, csv.Error, ValueError):
        raise ValueError('No se pudo leer el CSV con columna url') from None


def leer_semillas(ruta=SEMILLAS):
    if 'TIKTOK_CUENTAS' in os.environ:
        return list(dict.fromkeys(_canal(c.strip()) for c in
            os.environ['TIKTOK_CUENTAS'].split(',') if c.strip()))
    try:
        lineas = Path(ruta).read_text(encoding='utf-8-sig').splitlines()
        return list(dict.fromkeys(_canal(l.strip()) for l in lineas if l.strip()))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        raise ValueError('No se pudo leer el archivo de semillas: se esperan identificadores de cuenta') from None


def guardar_semillas(ruta, cuentas):
    previas = leer_semillas(ruta)
    nuevas = list(dict.fromkeys([*previas, *(_canal(c) for c in cuentas)]))
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix('.tmp')
    temporal.write_text(''.join(c+'\n' for c in nuevas), encoding='utf-8')
    temporal.replace(ruta)
    return len(nuevas) - len(previas)


def _cuentas_de_urls(urls, *, extractor=None, pausa=sleep, existentes=()):
    cuentas, vistos = [], set(existentes)
    fallidas = 0
    for i, url in enumerate(urls):
        if len(cuentas) >= 50:
            break
        if i:
            pausa(1.5)
        try:
            canal = canal_de(url, extractor=extractor)
        except ValueError:
            fallidas += 1
            continue
        if canal not in vistos:
            vistos.add(canal)
            cuentas.append(canal)
    return cuentas, {'cuentas_nuevas': len(cuentas), 'fallidas': fallidas}


def descubrir_cuentas(consultas, *, clave, pedir=None, extractor=None, pausa=sleep, existentes=()):
    consultas = _consultas(consultas)
    urls, vistos = [], set()
    fallidas = 0
    aviso = None
    proveedores, costo, tokens = [], 0, 0
    for consulta in consultas:
        detalle = {'consulta': len(proveedores)+1, 'proveedor': None, 'groq_tokens': 0}
        proveedores.append(detalle)
        try:
            encontradas, importe = buscar_urls(consulta, clave=clave, pedir=pedir,
                                        dominio='tiktok.com', validar_url=_validar_video, resumen=detalle)
        except LimiteBusqueda as error:
            if not urls:
                raise
            fallidas += 1
            aviso = str(error)
            break
        except ValueError:
            fallidas += 1
            continue
        costo += importe
        tokens += detalle['groq_tokens']
        for url in encontradas:
            nativo = id_desde_url(url)[1]
            if nativo not in vistos:
                vistos.add(nativo)
                urls.append(url)
    if fallidas == len(consultas):
        raise ValueError('OpenRouter/Groq: ninguna consulta de cuentas pudo completarse')
    cuentas, resumen = _cuentas_de_urls(urls, extractor=extractor, pausa=pausa, existentes=existentes)
    resumen['consultas_fallidas'] = fallidas
    resumen['aviso'] = aviso
    resumen.update(proveedores=proveedores, costo_usd=costo, groq_tokens=tokens)
    return cuentas, resumen


class FiltroTema:
    """Cuota compartida entre vueltas; el comando la conserva en disco entre ejecuciones."""
    def __init__(self, tema, *, clave, pedir=None, pausa=sleep, reloj=None, contador=None):
        terminos = terminos_tema(tema)
        self.hashtags = {normalizar_hashtag(t) for t in terminos if t.startswith('#')}
        self.terminos = [t for t in terminos if not t.startswith('#')]
        self.preciso = ',' in tema
        self.clave_groq = os.environ.get('GROQ_API_KEY', '').strip()
        self.groq_bloqueado = False
        self.ultimo_groq = None
        self.tema, self.clave = tema, clave
        self.pedir, self.pausa = pedir or _pedir, pausa
        self.reloj = reloj or (lambda:datetime.now(timezone.utc))
        self.contador = Path(contador) if contador else None
        self.dia, self.usados, self.ultimo = '', 0, None
        self.bloqueado = False
        if self.contador and self.contador.exists():
            try:
                datos = json.loads(self.contador.read_text(encoding='utf-8'))
                self.dia, self.usados = datos['dia'], datos['pedidos']
                if type(self.usados) is not int or not 0 <= self.usados <= 50:
                    raise ValueError()
            except (OSError, ValueError, KeyError, TypeError):
                raise ValueError('No se pudo leer el contador diario del filtro') from None

    def _reservar(self):
        dia = self.reloj().date().isoformat()
        if dia != self.dia:
            self.dia, self.usados = dia, 0
        if self.usados >= 50:
            return False
        # 3,1 s entre pedidos, incluidos reintentos: menos de 20 por minuto.
        if self.ultimo is not None:
            self.pausa(max(0, 3.1 - (monotonic() - self.ultimo)))
        elif self.contador:
            self.pausa(3.1)
        self.usados += 1
        if self.contador:
            self.contador.parent.mkdir(parents=True, exist_ok=True)
            temporal = self.contador.with_suffix('.tmp')
            temporal.write_text(json.dumps({'dia': self.dia, 'pedidos': self.usados}), encoding='utf-8')
            temporal.replace(self.contador)
        self.ultimo = monotonic()
        return True

    @staticmethod
    def _decisiones(respuesta, cantidad):
        valores = {}
        for linea in respuesta.strip().splitlines():
            match = re.fullmatch(r'\s*(\d+):\s*(SI|SÍ|NO)\s*', linea, flags=re.I)
            if not match or int(match[1]) in valores:
                raise ValueError()
            valores[int(match[1])] = match[2].upper() != 'NO'
        if set(valores) != set(range(1, cantidad+1)):
            raise ValueError()
        return valores

    def _espera_groq(self, error):
        headers = getattr(error, 'headers', None) or {}
        valor = headers.get('Retry-After') or headers.get('retry-after')
        try:
            segundos = float(valor)
        except (TypeError, ValueError):
            try:
                segundos = (parsedate_to_datetime(valor) - self.reloj()).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return 30
        return max(0, min(60, segundos)) if isfinite(segundos) else 30

    def filtrar(self, pares):
        originales = pares
        salida = [par for par in pares if self.hashtags.intersection(
            normalizar_hashtag(h) for h in par[0].hashtags)]
        directos = {p.id for p, _ in salida}
        pares = [par for par in pares if par[0].id not in directos]
        r = {'descartados_tema': 0, 'lotes_descartados_sin_filtro': 0, 'aviso': None,
             'lotes_openrouter': 0, 'lotes_groq': 0}
        if not self.terminos:
            r['descartados_tema'] = len(pares)
            return salida, r
        for inicio in range(0, len(pares), 30):
            lote = pares[inicio:inicio+30]
            decisiones = None
            # Los enlaces embebidos en la descripción tampoco se envían al modelo.
            textos = [re.sub(r'(?i)\b(?:https?://|www\.)\S+', '', texto_publico(p.texto or '')[0])
                      for p, _ in lote]
            criterio = ('específicamente de al menos uno de estos términos: ' +
                        '; '.join(self.terminos)) if self.preciso else 'de ' + self.terminos[0]
            prompt = (f"Para cada publicación, responde una línea 'n: SI' si trata {criterio}, "
                      "o 'n: NO' si no. Solo esas líneas, sin explicar.\n" +
                      '\n'.join(f'{i}: {texto}' for i, texto in enumerate(textos, 1)))
            for intento in range(2):
                if not self.clave or not self.clave.strip() or self.bloqueado or not self._reservar():
                    break
                cuerpo = {'model': 'nvidia/nemotron-3-super-120b-a12b:free',
                          'reasoning': {'enabled': False}, 'max_tokens': 500,
                          'messages': [{'role': 'user', 'content': prompt}]}
                try:
                    request = Request('https://openrouter.ai/api/v1/chat/completions',
                        data=json.dumps(cuerpo).encode('utf-8'),
                        headers={'Authorization':f'Bearer {self.clave}', 'Content-Type':'application/json'})
                    respuesta = self.pedir(request)['choices'][0]['message']['content']
                    decisiones = self._decisiones(respuesta, len(lote))
                    r['lotes_openrouter'] += 1
                    break
                except Exception as error:
                    if getattr(error, 'code', None) == 429:
                        self.bloqueado = True
                        break
                    if self.clave_groq:
                        break
            if decisiones is None and self.clave_groq and not self.groq_bloqueado:
                if self.ultimo_groq is not None:
                    transcurrido = (self.reloj() - self.ultimo_groq).total_seconds()
                    self.pausa(max(0, 30 - transcurrido))
                for intento in range(2):
                    self.ultimo_groq = self.reloj()
                    try:
                        request = _peticion_groq([{'role': 'user', 'content': prompt}], self.clave_groq)
                        respuesta = self.pedir(request)['choices'][0]['message']['content']
                        decisiones = self._decisiones(respuesta, len(lote))
                        r['lotes_groq'] += 1
                        break
                    except Exception as error:
                        codigo = getattr(error, 'code', None)
                        if codigo == 402 or (codigo == 429 and intento == 1):
                            self.groq_bloqueado = True
                            break
                        if intento == 0:
                            self.pausa(self._espera_groq(error) if codigo == 429 else 30)
            if decisiones is None:
                r['lotes_descartados_sin_filtro'] += 1
            else:
                salida.extend(par for i, par in enumerate(lote, 1) if decisiones[i])
                r['descartados_tema'] += sum(not v for v in decisiones.values())
        aceptados = {p.id for p, _ in salida}
        if r['lotes_descartados_sin_filtro']:
            r['aviso'] = (f"{r['lotes_descartados_sin_filtro']} lotes descartados: "
                          'no se pudieron filtrar con el tema')
        return [par for par in originales if par[0].id in aceptados], r


def capturar(cuentas, *, sal, dias=7, por_cuenta=30, maximo=300, listar=None,
             pausa=sleep, ahora=None, filtro=None):
    _entero(maximo, 1, 300, 'maximo')
    _entero(dias, 1, 36500, 'dias')
    _entero(por_cuenta, 1, 300, 'por_cuenta')
    if not sal or not sal.strip():
        raise ValueError('Falta AUTOR_HASH_SAL en el entorno')
    cuentas = list(dict.fromkeys(_canal(c) for c in cuentas))
    if not cuentas:
        raise ValueError('No hay cuentas semilla; ejecuta primero semillas')
    if filtro:
        filtro.bloqueado = False
        filtro.groq_bloqueado = False
    pares, vistos = [], set()
    r = dict(cuentas=0, cuentas_fallidas=0, videos=0, fuera_fecha=0, omitidos=0,
             descartados_tema=0, lotes_descartados_sin_filtro=0, lotes_openrouter=0, lotes_groq=0,
             aviso=None, interrumpido=False, detenido=False, motivos_fallo={})
    consecutivos = 0
    try:
        for i, canal in enumerate(cuentas):
            if len(pares) >= maximo:
                break
            if i:
                pausa(3)
            r['cuentas'] += 1
            try:
                ps, ms, resumen = videos_de_cuenta(canal, sal=sal, dias=dias,
                    por_cuenta=por_cuenta, listar=listar, ahora=ahora)
            except ValueError as error:
                r['cuentas_fallidas'] += 1
                motivo = error.categoria if isinstance(error, FalloTikTok) else 'otro'
                tipo = error.tipo if isinstance(error, FalloTikTok) else type(error).__name__
                r['motivos_fallo'][motivo] = r['motivos_fallo'].get(motivo, 0) + 1
                print(f'TikTok: {motivo} ({tipo})', file=sys.stderr)
                consecutivos += 1
                if isinstance(error, BloqueoTikTok) or consecutivos >= 3:
                    r['detenido'] = True
                    r['aviso'] = 'Captura detenida por bloqueo o tres cuentas fallidas consecutivas; salida parcial.'
                    break
                continue
            consecutivos = 0
            r['fuera_fecha'] += resumen['fuera_fecha']
            r['omitidos'] += resumen['omitidos']
            metricas = {m.publicacion_id:m for m in ms}
            for p in ps:
                if p.id not in vistos and len(pares) < maximo:
                    vistos.add(p.id)
                    pares.append((p, metricas.get(p.id)))
    except KeyboardInterrupt:
        r['interrumpido'] = True
    if filtro and not r['interrumpido']:
        try:
            pares, resumen = filtro.filtrar(pares)
            for campo in ('descartados_tema', 'lotes_descartados_sin_filtro', 'lotes_openrouter', 'lotes_groq'):
                r[campo] += resumen[campo]
            if resumen['aviso']:
                r['aviso'] = ' '.join(filter(None, (r['aviso'], resumen['aviso'])))
        except KeyboardInterrupt:
            r['interrumpido'] = True
    if filtro and r['interrumpido']:
        directos = [par for par in pares if filtro.hashtags.intersection(
            normalizar_hashtag(h) for h in par[0].hashtags)]
        r['lotes_descartados_sin_filtro'] = (len(pares) - len(directos) + 29)//30
        pares = directos
        if r['lotes_descartados_sin_filtro']:
            aviso = (f"{r['lotes_descartados_sin_filtro']} lotes descartados: "
                     'no se pudieron filtrar con el tema')
            r['aviso'] = ' '.join(filter(None, (r['aviso'], aviso)))
    r['videos'] = len(pares)
    return [p for p, _ in pares], [m for _, m in pares if m is not None], r


def _resumir(r):
    print(f"Cuentas: {r['cuentas']}; cuentas fallidas: {r['cuentas_fallidas']}; videos: {r['videos']}; "
          f"fuera de fecha: {r['fuera_fecha']}; omitidos: {r['omitidos']}; "
          f"descartados por tema: {r['descartados_tema']}; lotes descartados sin filtro: {r['lotes_descartados_sin_filtro']}", file=sys.stderr)
    print(f"Lotes OpenRouter: {r['lotes_openrouter']}; lotes Groq: {r['lotes_groq']}", file=sys.stderr)
    print(f"Motivos de fallo: {r['motivos_fallo']}", file=sys.stderr)
    if r['aviso']:
        print(r['aviso'], file=sys.stderr)


def ejecutar(cuentas, *, sal, salida_dir='data/raw/tiktok', cada_horas=None,
             reloj=None, pausa=sleep, filtro=None, **opciones):
    if cada_horas is not None and cada_horas < 1:
        raise ValueError('--cada-horas debe ser al menos 1')
    reloj = reloj or (lambda:datetime.now(timezone.utc))
    carpeta = Path(salida_dir)
    carpeta.mkdir(parents=True, exist_ok=True)
    bloqueo = carpeta / '.captura.lock'
    try:
        with bloqueo.open('x', encoding='ascii') as archivo:
            archivo.write(str(os.getpid()))
    except FileExistsError:
        raise ValueError('Ya hay otra captura en este directorio; comprueba el proceso antes de quitar .captura.lock') from None
    try:
        while True:
            ahora = reloj()
            ps, ms, r = capturar(cuentas, sal=sal, pausa=pausa, ahora=ahora, filtro=filtro, **opciones)
            ruta = carpeta / f"tiktok_{ahora:%Y-%m-%dT%H%M}.json"
            # Nunca sobrescribir otra observación lanzada durante el mismo minuto.
            if ruta.exists():
                ruta = carpeta / f"tiktok_{ahora:%Y-%m-%dT%H%M%S%f}.json"
            temporal = ruta.with_suffix('.tmp')
            try:
                with temporal.open('x', encoding='utf-8') as archivo:
                    from contextlib import redirect_stdout
                    with redirect_stdout(archivo):
                        imprimir_json(ps, ms)
                temporal.replace(ruta)
            finally:
                temporal.unlink(missing_ok=True)
            _resumir(r)
            if cada_horas is None or r['interrumpido'] or r['detenido']:
                break
            pausa(cada_horas * 3600)
    except KeyboardInterrupt:
        pass
    finally:
        bloqueo.unlink(missing_ok=True)


class _SinRedireccion(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # No reenviar X-Carga-Token a otro destino.
        return None


def _post_carga(request, *, timeout):
    with build_opener(_SinRedireccion()).open(request, timeout=timeout) as respuesta:
        if not 200 <= respuesta.status < 300:
            raise ValueError('El servicio rechazó la carga')


def subir(cuentas, *, servicio, sal, token, dias=7, cada_minutos=None, pedir=None, pausa=sleep):
    partes = urlsplit(servicio)
    if (partes.scheme not in ('http', 'https') or not partes.hostname or partes.username
            or partes.password or partes.query or partes.fragment):
        raise ValueError('--servicio requiere una URL base HTTP(S), sin credenciales')
    if not token or not token.strip():
        raise ValueError('Falta CARGA_TOKEN en el entorno')
    if not sal or not sal.strip():
        raise ValueError('Falta AUTOR_HASH_SAL en el entorno')
    _entero(dias, 1, 36500, 'dias')
    if cada_minutos is not None:
        _entero(cada_minutos, 1, 525600, 'cada_minutos')
    try:
        while True:
            interrumpido = False
            try:
                ps, ms, r = capturar(cuentas, sal=sal, dias=dias)
                interrumpido = r.get('interrumpido', False)
                print(f"TikTok: {len(ps)} publicaciones; detenida: {r.get('detenido', False)}; "
                      f"interrumpida: {interrumpido}", file=sys.stderr)
                if not ps or r.get('detenido') or interrumpido:
                    print('No se sube: captura vacía, detenida o interrumpida; se conserva la carga anterior.',
                          file=sys.stderr)
                else:
                    cuerpo = dict(publicaciones=[p.model_dump(mode='json') for p in ps],
                                  metricas=[m.model_dump(mode='json') for m in ms])
                    request = Request(servicio.rstrip('/') + '/tiktok/carga', method='POST',
                        data=json.dumps(cuerpo, ensure_ascii=False).encode('utf-8'),
                        headers={'Content-Type': 'application/json', 'X-Carga-Token': token})
                    (pedir or _post_carga)(request, timeout=90)
                    print(f'TikTok: carga confirmada, {len(ps)} publicaciones.', file=sys.stderr)
            except Exception:
                print('TikTok: captura o carga no confirmada; se conserva la carga anterior del servidor.',
                      file=sys.stderr)
            if cada_minutos is None or interrumpido:
                break
            pausa(cada_minutos * 60)
    except KeyboardInterrupt:
        print('Subida detenida por el usuario.', file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Cuentas semilla y capturas periódicas públicas de TikTok.')
    sub = parser.add_subparsers(dest='comando', required=True)
    semillas = sub.add_parser('semillas', help='Añadir hasta 50 cuentas, sin duplicados')
    fuente = semillas.add_mutually_exclusive_group(required=True)
    fuente.add_argument('--desde-csv', type=Path)
    fuente.add_argument('--consulta', action='append', help='Exa: máximo 20 consultas')
    semillas.add_argument('--semillas', type=Path, default=SEMILLAS)
    captura = sub.add_parser('capturar', help='Guardar publicaciones y métricas nuevas')
    captura.add_argument('--semillas', type=Path, default=SEMILLAS)
    captura.add_argument('--dias', type=int, default=7)
    captura.add_argument('--por-cuenta', type=int, default=30)
    captura.add_argument('--max', dest='maximo', type=int, default=300)
    captura.add_argument('--salida-dir', type=Path, default=Path('data/raw/tiktok'))
    captura.add_argument('--cada-horas', type=int)
    captura.add_argument('--tema', help='Frase amplia o hasta 5 términos por comas; #hashtag exacto sin modelo')
    subida = sub.add_parser('subir', help='Capturar sin tema y subir al servicio; sin intervalo hace una vuelta')
    subida.add_argument('--servicio', required=True)
    subida.add_argument('--semillas', type=Path, default=SEMILLAS)
    subida.add_argument('--dias', type=int, default=7)
    subida.add_argument('--cada-minutos', type=int)
    args = parser.parse_args(argv)
    try:
        cuentas = leer_semillas(args.semillas)
        if args.comando == 'semillas':
            if args.consulta:
                clave = os.environ.get('OPENROUTER_API_KEY', '')
                if not clave.strip() and not os.environ.get('GROQ_API_KEY', '').strip():
                    raise ValueError('Falta OPENROUTER_API_KEY en el entorno')
                nuevas, resumen = descubrir_cuentas(args.consulta, clave=clave, existentes=cuentas)
            else:
                nuevas, resumen = _cuentas_de_urls(urls_desde_csv(args.desde_csv), existentes=cuentas)
            cantidad = guardar_semillas(args.semillas, nuevas)
            print(f"Cuentas nuevas: {cantidad}; fallidas: {resumen['fallidas']}; "
                  f"consultas fallidas: {resumen.get('consultas_fallidas', 0)}", file=sys.stderr)
            if 'proveedores' in resumen:
                print(f"Proveedores por consulta: {resumen['proveedores']}; costo OpenRouter: USD "
                      f"{resumen['costo_usd']:.6f}; tokens Groq: {resumen['groq_tokens']}", file=sys.stderr)
            if resumen.get('aviso'):
                print(resumen['aviso'], file=sys.stderr)
        elif args.comando == 'subir':
            if not cuentas:
                raise ValueError('No hay cuentas semilla; ejecuta primero semillas')
            subir(cuentas, servicio=args.servicio, dias=args.dias, cada_minutos=args.cada_minutos,
                  sal=os.environ.get('AUTOR_HASH_SAL', ''), token=os.environ.get('CARGA_TOKEN', ''))
        else:
            if not cuentas:
                raise ValueError('No hay cuentas semilla; ejecuta primero semillas')
            filtro = FiltroTema(args.tema, clave=os.environ.get('OPENROUTER_API_KEY', ''),
                               contador=Path('data/raw/tiktok_filtro_cuota.json')) if args.tema is not None else None
            ejecutar(cuentas, sal=os.environ.get('AUTOR_HASH_SAL', ''), dias=args.dias,
                     por_cuenta=args.por_cuenta, maximo=args.maximo, salida_dir=args.salida_dir,
                     cada_horas=args.cada_horas, filtro=filtro)
    except (ValueError, OSError):
        # Solo los errores propios de validación se muestran, nunca rutas ni datos del proveedor.
        error = sys.exc_info()[1]
        mensaje = str(error) if isinstance(error, ValueError) else 'No se pudieron leer o guardar los archivos locales'
        parser.exit(1, f'Error: {mensaje}\n')
    except KeyboardInterrupt:
        parser.exit(130, 'Detenido por el usuario\n')


if __name__ == '__main__':
    main()
