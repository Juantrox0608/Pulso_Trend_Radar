"""Captura periódica de cuentas semilla públicas de TikTok, sin sesión ni descarga."""
import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from io import StringIO
from itertools import islice
from pathlib import Path
from time import sleep, monotonic
from urllib.parse import urlsplit
from urllib.request import Request

import yt_dlp

from radar.contrato import Plataforma, id_desde_url
from radar.recoleccion import imprimir_json, texto_publico, terminos_tema, normalizar_hashtag, tiktok
from radar.recoleccion.linkedin_buscar import buscar_urls, _consultas, _entero, _pedir

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
        return list(ydl.extract_info('tiktokuser:' + channel_id, download=False)['entries'])


class BloqueoTikTok(ValueError):
    pass


def _bloqueo(error):
    # yt-dlp puede envolver el HTTPError en DownloadError y conservar solo el mensaje.
    while error is not None:
        if getattr(error, 'code', None) in (403, 429) or re.search(
                r'(?i)(?:HTTP(?: Error)?[ :]+|status(?: code)?[ :]+)(?:403|429)\b', str(error)):
            return True
        error = error.__cause__ or error.__context__
    return False


def videos_de_cuenta(channel_id, *, sal, dias=7, por_cuenta=30, listar=None, ahora=None):
    _canal(channel_id)
    _entero(dias, 1, 36500, 'dias')
    _entero(por_cuenta, 1, 300, 'por_cuenta')
    ahora = ahora or datetime.now(timezone.utc)
    desde = ahora - timedelta(days=dias)
    publicaciones, metricas = [], []
    resumen = {'fuera_fecha': 0, 'omitidos': 0}
    try:
        entradas = list(islice(iter((listar or _listar)(channel_id, por_cuenta)), por_cuenta))
    except Exception as error:
        if _bloqueo(error):
            raise BloqueoTikTok('Bloqueo HTTP de TikTok: captura detenida sin reintentos') from None
        raise ValueError('TikTok: no se pudo listar una cuenta pública') from None
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
    for consulta in consultas:
        try:
            encontradas, _ = buscar_urls(consulta, clave=clave, pedir=pedir,
                                        dominio='tiktok.com', validar_url=_validar_video)
        except ValueError:
            fallidas += 1
            continue
        for url in encontradas:
            nativo = id_desde_url(url)[1]
            if nativo not in vistos:
                vistos.add(nativo)
                urls.append(url)
    if fallidas == len(consultas):
        raise ValueError('OpenRouter: ninguna consulta de cuentas pudo completarse')
    cuentas, resumen = _cuentas_de_urls(urls, extractor=extractor, pausa=pausa, existentes=existentes)
    resumen['consultas_fallidas'] = fallidas
    return cuentas, resumen


class FiltroTema:
    """Cuota compartida entre vueltas; el comando la conserva en disco entre ejecuciones."""
    def __init__(self, tema, *, clave, pedir=None, pausa=sleep, reloj=None, contador=None):
        terminos = terminos_tema(tema)
        self.hashtags = {normalizar_hashtag(t) for t in terminos if t.startswith('#')}
        self.terminos = [t for t in terminos if not t.startswith('#')]
        self.preciso = ',' in tema
        if self.terminos and (not clave or not clave.strip()):
            raise ValueError('Falta OPENROUTER_API_KEY en el entorno para --tema')
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

    def filtrar(self, pares):
        originales = pares
        salida = [par for par in pares if self.hashtags.intersection(
            normalizar_hashtag(h) for h in par[0].hashtags)]
        directos = {p.id for p, _ in salida}
        pares = [par for par in pares if par[0].id not in directos]
        r = {'descartados_tema': 0, 'lotes_sin_filtrar': 0, 'aviso': None}
        if not self.terminos:
            r['descartados_tema'] = len(pares)
            return salida, r
        for inicio in range(0, len(pares), 30):
            lote = pares[inicio:inicio+30]
            decisiones = None
            for intento in range(2):
                if self.bloqueado or not self._reservar():
                    r['aviso'] = 'Filtro detenido por cuota o HTTP 429; se conservan lotes sin filtrar.'
                    break
                # Los enlaces embebidos en la descripción tampoco se envían al modelo.
                textos = [re.sub(r'(?i)\b(?:https?://|www\.)\S+', '', texto_publico(p.texto or '')[0])
                          for p, _ in lote]
                criterio = ('específicamente de al menos uno de estos términos: ' +
                            '; '.join(self.terminos)) if self.preciso else 'de ' + self.terminos[0]
                prompt = (f"Para cada publicación, responde una línea 'n: SI' si trata {criterio}, "
                          "o 'n: NO' si no. Solo esas líneas, sin explicar.\n" +
                          '\n'.join(f'{i}: {texto}' for i, texto in enumerate(textos, 1)))
                cuerpo = {'model': 'nvidia/nemotron-3-super-120b-a12b:free',
                          'reasoning': {'enabled': False}, 'max_tokens': 500,
                          'messages': [{'role': 'user', 'content': prompt}]}
                try:
                    request = Request('https://openrouter.ai/api/v1/chat/completions',
                        data=json.dumps(cuerpo).encode('utf-8'),
                        headers={'Authorization':f'Bearer {self.clave}', 'Content-Type':'application/json'})
                    respuesta = self.pedir(request)['choices'][0]['message']['content']
                    lineas = respuesta.strip().splitlines()
                    valores = {}
                    for linea in lineas:
                        match = re.fullmatch(r'\s*(\d+):\s*(SI|SÍ|NO)\s*', linea, flags=re.I)
                        if not match or int(match[1]) in valores:
                            raise ValueError()
                        valores[int(match[1])] = match[2].upper() != 'NO'
                    if set(valores) != set(range(1, len(lote)+1)):
                        raise ValueError()
                    decisiones = valores
                    break
                except Exception as error:
                    if getattr(error, 'code', None) == 429:
                        self.bloqueado = True
                        r['aviso'] = 'Filtro detenido por HTTP 429; se conservan lotes sin filtrar.'
                        break
            if decisiones is None:
                salida.extend(lote)
                r['lotes_sin_filtrar'] += 1
            else:
                salida.extend(par for i, par in enumerate(lote, 1) if decisiones[i])
                r['descartados_tema'] += sum(not v for v in decisiones.values())
        aceptados = {p.id for p, _ in salida}
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
    pares, vistos = [], set()
    r = dict(cuentas=0, cuentas_fallidas=0, videos=0, fuera_fecha=0, omitidos=0,
             descartados_tema=0, lotes_sin_filtrar=0, aviso=None, interrumpido=False, detenido=False)
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
            for campo in ('descartados_tema', 'lotes_sin_filtrar'):
                r[campo] += resumen[campo]
            if resumen['aviso']:
                r['aviso'] = ' '.join(filter(None, (r['aviso'], resumen['aviso'])))
        except KeyboardInterrupt:
            r['interrumpido'] = True
            r['lotes_sin_filtrar'] += (len(pares)+29)//30
    r['videos'] = len(pares)
    return [p for p, _ in pares], [m for _, m in pares if m is not None], r


def _resumir(r):
    print(f"Cuentas: {r['cuentas']}; cuentas fallidas: {r['cuentas_fallidas']}; videos: {r['videos']}; "
          f"fuera de fecha: {r['fuera_fecha']}; omitidos: {r['omitidos']}; "
          f"descartados por tema: {r['descartados_tema']}; lotes sin filtrar: {r['lotes_sin_filtrar']}", file=sys.stderr)
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
    args = parser.parse_args(argv)
    try:
        cuentas = leer_semillas(args.semillas)
        if args.comando == 'semillas':
            if args.consulta:
                clave = os.environ.get('OPENROUTER_API_KEY', '')
                if not clave.strip():
                    raise ValueError('Falta OPENROUTER_API_KEY en el entorno')
                nuevas, resumen = descubrir_cuentas(args.consulta, clave=clave, existentes=cuentas)
            else:
                nuevas, resumen = _cuentas_de_urls(urls_desde_csv(args.desde_csv), existentes=cuentas)
            cantidad = guardar_semillas(args.semillas, nuevas)
            print(f"Cuentas nuevas: {cantidad}; fallidas: {resumen['fallidas']}; "
                  f"consultas fallidas: {resumen.get('consultas_fallidas', 0)}", file=sys.stderr)
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
