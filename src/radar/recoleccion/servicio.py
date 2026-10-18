"""Servicio de pruebas: una búsqueda en un hilo y resultados temporales."""
import os
from secrets import compare_digest
from threading import Lock, Thread
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from radar.recoleccion import buscar


class Busqueda(BaseModel):
    model_config = ConfigDict(extra='forbid')

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
    app = FastAPI(title='Radar · Recolección', version='0.1', redoc_url=None)
    recolector = recolector or buscar.recolectar
    cerrojo = Lock()
    # shortcut: en memoria, se pierde al reiniciar Render; pasar a la base del equipo al unir
    busquedas = {}

    @app.middleware('http')
    async def autenticar(request, call_next):
        # La documentación es pública; las búsquedas siguen protegidas si hay RADAR_TOKEN.
        if request.url.path not in ('/salud', '/docs', '/openapi.json'):
            esperado = os.environ.get('RADAR_TOKEN', '')
            recibido = request.headers.get('X-Token', '')
            if esperado and not compare_digest(recibido.encode('utf-8'), esperado.encode('utf-8')):
                return JSONResponse({'detail': 'Token inválido'}, status_code=401)
        return await call_next(request)

    def ejecutar(id, datos):
        try:
            ps, ms, resumen = recolector(datos.tema, dias=datos.dias,
                                        redes=datos.redes, paises=datos.paises)
            resultado = dict(estado='lista', resumen=resumen,
                publicaciones=[p.model_dump(mode='json') for p in ps],
                metricas=[m.model_dump(mode='json') for m in ms])
        except Exception:
            resultado = dict(estado='error', resumen={}, mensaje='No se pudo completar la búsqueda')
        with cerrojo:
            busquedas[id] = resultado

    @app.get('/salud')
    def salud():
        return {'estado': 'ok'}

    @app.post('/busquedas', status_code=202)
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

    @app.get('/busquedas/{id}')
    def consultar(id: str):
        with cerrojo:
            if id not in busquedas:
                raise HTTPException(404, 'Búsqueda no encontrada')
            return busquedas[id]

    return app


app = crear_app()
