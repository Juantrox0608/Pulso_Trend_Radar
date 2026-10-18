"""Búsqueda por tema en tres redes y envío opcional de una copia guardada."""
import argparse
import json
import os
import re
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from radar.recoleccion import imprimir_json, terminos_tema, youtube, linkedin_buscar, tiktok_cuentas

REDES = ('youtube', 'linkedin', 'tiktok')
PAISES = ('MX', 'CO', 'AR', 'CL', 'PE')


def _youtube(tema, dias, pais):
    return youtube.buscar_con_metricas(tema, pais, 'es', datetime.now(timezone.utc)-timedelta(days=dias))


def _linkedin(tema, dias):
    return linkedin_buscar.descubrir([tema], dias=dias,
        clave=os.environ.get('OPENROUTER_API_KEY', ''), sal=os.environ.get('AUTOR_HASH_SAL', ''))


def _tiktok(tema, dias):
    filtro = tiktok_cuentas.FiltroTema(tema, clave=os.environ.get('OPENROUTER_API_KEY', ''),
                                    contador=Path('data/raw/tiktok_filtro_cuota.json'))
    return tiktok_cuentas.capturar(tiktok_cuentas.leer_semillas(), dias=dias, filtro=filtro,
                                  sal=os.environ.get('AUTOR_HASH_SAL', ''))


def validar_busqueda(tema, dias, redes, paises):
    if not tema.strip() or not 1 <= dias <= 36500:
        raise ValueError('Usa un tema con texto y --dias entre 1 y 36500')
    terminos = terminos_tema(tema)
    redes = list(dict.fromkeys(redes))
    paises = list(dict.fromkeys(p.strip().upper() for p in paises))
    if not redes or any(r not in REDES for r in redes):
        raise ValueError('--redes admite youtube,linkedin,tiktok')
    if not paises or any(not re.fullmatch('[A-Z]{2}', p) for p in paises):
        raise ValueError('--paises requiere códigos de dos letras')
    return terminos, redes, paises


def recolectar(tema, *, dias=7, redes=REDES, paises=PAISES, recolectores=None):
    terminos, redes, paises = validar_busqueda(tema, dias, redes, paises)
    recolectores = recolectores or dict(youtube=_youtube, linkedin=_linkedin, tiktok=_tiktok)
    publicaciones, metricas, resumen = {}, {}, {}
    exitos = 0
    for red in redes:
        r = dict(publicaciones=0, metricas=0, fallidas=0)
        resumen[red] = r
        consultas = [(t, p) for t in terminos for p in paises] if red == 'youtube' else [
            (t, None) for t in (terminos if red == 'linkedin' else [tema])]
        for consulta, pais in consultas:
            try:
                resultado = recolectores[red](consulta, dias, pais) if pais else recolectores[red](consulta, dias)
            except Exception:
                r['fallidas'] += 1
                r['aviso'] = ('No se completaron una o más consultas; revisa YOUTUBE_API_KEY y AUTOR_HASH_SAL'
                    if red == 'youtube' else
                    'No se completó la red; revisa OPENROUTER_API_KEY, GROQ_API_KEY, AUTOR_HASH_SAL, saldo y acceso público')
                continue
            exitos += 1
            ps, ms = resultado[:2]
            if len(resultado) > 2:
                detalle = resultado[2]
                if red == 'linkedin' and 'detalle' in r:
                    anteriores = r['detalle'].get('consultas', 0)
                    for campo in ('consultas', 'consultas_extra', 'consultas_fallidas', 'urls', 'completados',
                                  'omitidos', 'fuera_fecha', 'costo_usd', 'groq_tokens'):
                        r['detalle'][campo] = r['detalle'].get(campo, 0) + detalle.get(campo, 0)
                    r['detalle'].setdefault('proveedores', []).extend(
                        dict(p, consulta=p['consulta']+anteriores) for p in detalle.get('proveedores', []))
                    avisos = dict.fromkeys(filter(None, (r['detalle'].get('aviso'), detalle.get('aviso'))))
                    r['detalle']['aviso'] = ' '.join(avisos) or None
                else:
                    r['detalle'] = dict(detalle)
            for p in ps:
                if p.id not in publicaciones:
                    publicaciones[p.id] = p
                    r['publicaciones'] += 1
            for m in ms:
                # Una sola observación por pieza en esta búsqueda, aunque salga en varios países.
                if m.publicacion_id not in metricas:
                    metricas[m.publicacion_id] = m
                    r['metricas'] += 1
    if not exitos:
        fallos = '; '.join(f'{red}: {r["fallidas"]} consultas fallidas' for red,r in resumen.items())
        raise ValueError('Todas las redes fallaron; ' + fallos +
            '; revisa YOUTUBE_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY, AUTOR_HASH_SAL, saldo y conexión')
    return list(publicaciones.values()), list(metricas.values()), resumen


def _post(request, *, timeout):
    with urlopen(request, timeout=timeout) as respuesta:
        if not 200 <= respuesta.status < 300:
            raise ValueError('La API rechazó el lote')


def enviar(url, publicaciones, metricas, *, pedir=None):
    partes = urlsplit(url)
    if (partes.scheme not in ('http', 'https') or not partes.hostname or partes.username
            or partes.password or partes.query or partes.fragment):
        raise ValueError('--enviar requiere la URL base HTTP(S) de la API, sin credenciales')
    fallidos = []
    for inicio in range(0, len(publicaciones), 200):
        lote = publicaciones[inicio:inicio+200]
        ids = {p.id for p in lote}
        cuerpo = dict(publicaciones=[p.model_dump(mode='json') for p in lote],
                      metricas=[m.model_dump(mode='json') for m in metricas if m.publicacion_id in ids])
        request = Request(url.rstrip('/')+'/api/publicaciones', method='POST',
            data=json.dumps(cuerpo, ensure_ascii=False).encode('utf-8'), headers={'Content-Type':'application/json'})
        try:
            (pedir or _post)(request, timeout=30)
        except Exception:
            fallidos.append(inicio//200+1)
    return fallidos


def main(argv=None):
    parser = argparse.ArgumentParser(description='Busca un tema en YouTube, LinkedIn y TikTok.')
    parser.add_argument('--tema', required=True, help='Frase amplia o hasta 5 términos por comas; admite #hashtag')
    parser.add_argument('--dias', type=int, default=7)
    parser.add_argument('--redes', default=','.join(REDES))
    parser.add_argument('--paises', default=','.join(PAISES))
    parser.add_argument('--salida', type=Path)
    parser.add_argument('--enviar', help='URL base de la API; guarda una copia antes del POST')
    args = parser.parse_args(argv)
    try:
        ps, ms, resumen = recolectar(args.tema, dias=args.dias,
            redes=args.redes.split(','), paises=args.paises.split(','))
        for red, r in resumen.items():
            print(f'{red}: {r}', file=sys.stderr)
        salida = args.salida
        if args.enviar and salida is None:
            salida = Path('data/raw') / f'busqueda_{datetime.now(timezone.utc):%Y-%m-%dT%H%M%S%f}.json'
        if salida:
            salida.parent.mkdir(parents=True, exist_ok=True)
            with salida.open('w', encoding='utf-8') as archivo, redirect_stdout(archivo):
                imprimir_json(ps, ms)
        else:
            imprimir_json(ps, ms)
        if args.enviar:
            fallidos = enviar(args.enviar, ps, ms)
            if fallidos:
                parser.exit(1, 'Error: lotes no confirmados (sin reintentos): ' +
                    ', '.join(map(str, fallidos)) + '; copia local conservada.\n')
    except (ValueError, OSError) as error:
        mensaje = str(error) if isinstance(error, ValueError) else 'No se pudo guardar la salida local'
        parser.exit(1, f'Error: {mensaje}\n')


if __name__ == '__main__':
    main()
