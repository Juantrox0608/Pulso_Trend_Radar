"""Servicio de pruebas: una búsqueda en un hilo y resultados temporales."""
import os
from datetime import datetime, timezone
from secrets import compare_digest
from threading import Lock, Thread
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from radar.recoleccion import buscar
from radar.contrato import Publicacion, Metrica


class CargaTikTok(BaseModel):
    model_config = ConfigDict(extra='forbid')

    publicaciones: list[Publicacion] = Field(max_length=3000)
    metricas: list[Metrica] = Field(max_length=3000)

    @model_validator(mode='after')
    def validar(self):
        ids = {p.id for p in self.publicaciones}
        if len(ids) != len(self.publicaciones) or any(not id.startswith('tt:') for id in ids):
            raise ValueError('Solo publicaciones TikTok sin duplicados')
        if any(m.publicacion_id not in ids for m in self.metricas):
            raise ValueError('Las métricas deben pertenecer a las publicaciones TikTok cargadas')
        if len({m.publicacion_id for m in self.metricas}) != len(self.metricas):
            raise ValueError('Solo una métrica por publicación')
        return self


class Busqueda(BaseModel):
    model_config = ConfigDict(extra='forbid', json_schema_extra={'examples': [
        {'tema': 'agentes de IA en empresas', 'redes': ['youtube', 'linkedin', 'tiktok'], 'dias': 7, 'paises': ['MX', 'CO']},
        {'tema': 'ciberseguridad, hacking, fraude digital', 'redes': ['youtube'], 'dias': 7, 'paises': ['CO']},
        {'tema': '#ia', 'redes': ['tiktok'], 'dias': 7}]})

    tema: str
    redes: list[str] = Field(default_factory=lambda: list(buscar.REDES))
    dias: int = Field(default=7, strict=True, ge=1, le=36500)
    paises: list[str] = Field(default_factory=lambda: list(buscar.PAISES))

    @model_validator(mode='after')
    def validar(self):
        _, self.redes, self.paises = buscar.validar_busqueda(
            self.tema, self.dias, self.redes, self.paises)
        return self


def crear_app(*, recolector=None):
    app = FastAPI(title='Radar · Recolección', version='0.2', redoc_url=None, description=(
        'Recolecta publicaciones públicas de YouTube, LinkedIn y TikTok con sus métricas, sin autores ni @usuarios. '
        'Flujo: `POST /busquedas` devuelve un `id`; consultar `GET /busquedas/{id}` hasta `estado: lista` '
        '(1–5 minutos). Una búsqueda a la vez. TikTok se sirve desde lo que sube la PC del equipo '
        '(`POST /tiktok/carga`), porque TikTok bloquea los servidores de Render. Si el servidor define '
        '`RADAR_TOKEN`, las búsquedas exigen la cabecera `X-Token`.'))
    cerrojo = Lock()
    # shortcut: en memoria, se pierde al reiniciar Render; pasar a la base del equipo al unir
    busquedas = {}
    carga = ([], [], None)

    @app.middleware('http')
    async def autenticar(request, call_next):
        if request.url.path.rstrip('/') == '/tiktok/carga':
            if request.method == 'POST':
                esperado = os.environ.get('CARGA_TOKEN', '')
                if not esperado:
                    return JSONResponse({'detail': 'Falta CARGA_TOKEN en el servidor'}, status_code=503)
                recibido = request.headers.get('X-Carga-Token', '')
                if not compare_digest(recibido.encode('utf-8'), esperado.encode('utf-8')):
                    return JSONResponse({'detail': 'Token inválido'}, status_code=401)
            return await call_next(request)
        # La documentación es pública; las búsquedas siguen protegidas si hay RADAR_TOKEN.
        if request.url.path not in ('/salud', '/docs', '/openapi.json'):
            esperado = os.environ.get('RADAR_TOKEN', '')
            recibido = request.headers.get('X-Token', '')
            if esperado and not compare_digest(recibido.encode('utf-8'), esperado.encode('utf-8')):
                return JSONResponse({'detail': 'Token inválido'}, status_code=401)
        return await call_next(request)

    def ejecutar(id, datos):
        try:
            opciones = dict(dias=datos.dias, redes=datos.redes, paises=datos.paises)
            if recolector is None and os.environ.get('TIKTOK_DESDE_CARGA') == '1':
                with cerrojo:
                    opciones['carga_tiktok'] = carga
            ps, ms, resumen = (recolector or buscar.recolectar)(datos.tema, **opciones)
            resultado = dict(estado='lista', resumen=resumen,
                publicaciones=[p.model_dump(mode='json') for p in ps],
                metricas=[m.model_dump(mode='json') for m in ms])
        except Exception:
            resultado = dict(estado='error', resumen={}, mensaje='No se pudo completar la búsqueda')
        with cerrojo:
            busquedas[id] = resultado

    @app.get('/salud', tags=['Servicio'], summary='Salud del servicio',
             description='No pide token ni llama a proveedores. Sirve para despertar el servicio gratis de Render.')
    def salud():
        return {'estado': 'ok'}

    @app.post('/tiktok/carga', tags=['TikTok'], summary='Subir captura de TikTok (solo la PC del equipo)',
              description='Reemplaza los videos de TikTok guardados en memoria. Exige la cabecera `X-Carga-Token`. '
                          'Solo ids `tt:`, máximo 3000, una métrica por publicación. Lo usa el comando '
                          '`python -m radar.recoleccion.tiktok_cuentas subir`.')
    def cargar(datos: CargaTikTok):
        nonlocal carga
        with cerrojo:
            carga = (datos.publicaciones, datos.metricas, datetime.now(timezone.utc).isoformat())
            return {'publicaciones': len(carga[0]), 'cargado_en': carga[2]}

    @app.get('/tiktok/carga', tags=['TikTok'], summary='Ver cuántos videos de TikTok hay cargados',
             description='Devuelve la cantidad de publicaciones cargadas y la hora de la última carga (UTC). No pide token.')
    def estado_carga():
        with cerrojo:
            return {'publicaciones': len(carga[0]), 'cargado_en': carga[2]}

    @app.post('/busquedas', status_code=202, tags=['Búsquedas'], summary='Iniciar una búsqueda',
              description='`tema`: frase amplia o hasta 5 términos por comas (más preciso); admite `#hashtag` exacto. '
                          '`redes`: youtube, linkedin, tiktok (por defecto las tres). `dias`: ventana de publicación '
                          '(por defecto 7). `paises`: códigos de dos letras, solo afectan a YouTube. Responde 202 con '
                          'el `id`; 409 si ya hay una búsqueda en curso; 422 si la entrada no es válida. '
                          'No reintentar automáticamente.')
    def iniciar(datos: Busqueda):
        with cerrojo:
            if any(b['estado'] == 'en_curso' for b in busquedas.values()):
                raise HTTPException(409, 'Ya hay una búsqueda en curso')
            id = uuid4().hex
            busquedas[id] = dict(estado='en_curso', resumen={})
            if len(busquedas) > 20:
                del busquedas[next(iter(busquedas))]
            try:
                Thread(target=ejecutar, args=(id, datos), daemon=True).start()
            except Exception:
                del busquedas[id]
                raise HTTPException(503, 'No se pudo iniciar la búsqueda') from None
        return dict(id=id, estado='en_curso')

    @app.get('/busquedas/{id}', tags=['Búsquedas'], summary='Consultar una búsqueda',
             description='`estado`: `en_curso`, `lista` o `error`. En `lista` trae `publicaciones` y `metricas` del contrato '
                         '(ids `yt:`, `li:`, `tt:`; vacío es `null`, no 0) y un `resumen` por red con avisos y fallos. '
                         'En LinkedIn `likes` es el total de reacciones. Los resultados viven en memoria (máximo 20) '
                         'y se pierden si Render reinicia: 404.')
    def consultar(id: str):
        with cerrojo:
            if id not in busquedas:
                raise HTTPException(404, 'Búsqueda no encontrada')
            return busquedas[id]

    return app


app = crear_app()
