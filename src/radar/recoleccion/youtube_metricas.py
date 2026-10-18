"""Recaptura de estadísticas de videos conocidos, sin repetir búsquedas."""
import argparse
import json
import os
import re
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from radar.contrato import Metrica, Plataforma, id_contrato
from radar.recoleccion import imprimir_json
from radar.recoleccion.youtube import _pedir_json


def recapturar(entradas, *, peticion=None):
    clave = os.environ.get('YOUTUBE_API_KEY', '')
    if not clave.strip():
        raise ValueError('Falta la variable de entorno YOUTUBE_API_KEY')
    ids = {}
    try:
        for ruta in entradas:
            datos = json.loads(Path(ruta).read_text(encoding='utf-8-sig'))
            publicaciones = datos['publicaciones'] if isinstance(datos, dict) else datos
            if not isinstance(publicaciones, list):
                raise ValueError()
            for p in publicaciones:
                identificador = p['id']
                if identificador.startswith('yt:'):
                    ids[id_contrato(Plataforma.YOUTUBE, identificador[3:])[3:]] = None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ValueError('Entrada inválida: se esperan JSON con publicaciones e ids válidos') from None
    ids = list(ids)
    metricas = []
    resumen = dict(ids=len(ids), llamadas=0, metricas=0, faltantes=0)
    for inicio in range(0, len(ids), 50):
        lote = ids[inicio:inicio+50]
        ahora = datetime.now(timezone.utc)
        respuesta = (peticion or _pedir_json)('videos', {
            'part': 'statistics', 'id': ','.join(lote), 'key': clave,
            'fields': 'items(id,statistics(viewCount,likeCount,commentCount))'})
        resumen['llamadas'] += 1
        try:
            vistos = set()
            for video in respuesta['items']:
                nativo = video['id']
                if nativo not in lote or nativo in vistos:
                    raise ValueError()
                vistos.add(nativo)
                conteos = {}
                for campo, externo in (('vistas','viewCount'), ('likes','likeCount'), ('comentarios','commentCount')):
                    valor = video.get('statistics', {}).get(externo)
                    if valor is not None:
                        if isinstance(valor, bool) or not re.fullmatch('[0-9]+', str(valor)):
                            raise ValueError()
                        conteos[campo] = int(valor)
                if conteos:
                    metricas.append(Metrica(publicacion_id='yt:'+nativo, capturada_en=ahora,
                                           origen='api_oficial', **conteos))
            resumen['faltantes'] += len(set(lote) - vistos)
        except (KeyError, TypeError, ValueError):
            raise ValueError('YouTube devolvió estadísticas inválidas') from None
    resumen['metricas'] = len(metricas)
    return metricas, resumen


def main(argv=None):
    parser = argparse.ArgumentParser(description='Recaptura métricas YouTube en lotes de 50 ids.')
    parser.add_argument('entradas', nargs='+', type=Path)
    parser.add_argument('--salida', type=Path)
    args = parser.parse_args(argv)
    try:
        metricas, r = recapturar(args.entradas)
        if args.salida:
            args.salida.parent.mkdir(parents=True, exist_ok=True)
            with args.salida.open('w', encoding='utf-8') as archivo, redirect_stdout(archivo):
                imprimir_json([], metricas)
        else:
            imprimir_json([], metricas)
    except (ValueError, RuntimeError, OSError) as error:
        mensaje = str(error) if not isinstance(error, OSError) else 'No se pudo guardar la salida'
        parser.exit(1, f'Error: {mensaje}\n')
    print('; '.join(f'{k}: {v}' for k,v in r.items()), file=sys.stderr)


if __name__ == '__main__':
    main()
