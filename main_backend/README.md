# Backend principal de 30X RADAR

Flujo real: frontend → `POST /research` → recolector desplegado → normalización y
selección → `POST /analyze` del servicio IA → frontend. Sin base de datos ni
persistencia de investigaciones. No hay datos quemados ni fallback simulado en
ejecución. Los fixtures existen únicamente en las pruebas automáticas.

La conexión HTTP con IA conserva su contrato y cliente. Este cambio no fusiona
los dos procesos; puedes seguir usando la IA ya desplegada.

## Contrato confirmado del recolector

Verificado contra el [OpenAPI desplegado](https://radar-recoleccion.onrender.com/openapi.json)
y el código de `origin/feature/recoleccion`, referencia `f3386ab`:
`src/radar/recoleccion/servicio.py`, `buscar.py` y `contrato/metrica.py`.
El OpenAPI no describe los cuerpos de respuesta; se confirmaron en implementación
y en una prueba real. Se leyó la rama remota sin cambiar de rama ni fusionarla.

- `GET /salud` → `{"estado":"ok"}`. No requiere token en este despliegue.
- `POST /busquedas` → HTTP 202, `{"id":"<uuid hexadecimal de 32 caracteres>","estado":"en_curso"}`.
- `GET /busquedas/{id}` → HTTP 200: `en_curso`, `lista` o `error`.
- `lista` contiene `resumen`, `publicaciones` y `metricas`.
- `error` indica búsqueda fallida. HTTP 409 al crear indica que hay otra en curso.
- HTTP 404 al consultar puede indicar que se perdió la búsqueda: el recolector
  guarda hasta 20 tareas en memoria y las pierde al reiniciarse.
- Redes admitidas por el recolector: youtube, linkedin, tiktok. Este backend y
  el contrato de IA siguen admitiendo **solo YouTube**.
- `dias`: entero 1–36500; `paises`: lista no vacía de códigos de dos letras;
  tema: una frase o de uno a cinco términos distintos separados por comas.

Ejemplo de creación:

```json
{"tema":"inteligencia artificial","redes":["youtube"],"dias":7,"paises":["CO"]}
```

Ejemplo estructural de resultado, con datos ficticios de documentación:

```json
{
  "estado": "lista",
  "resumen": {"youtube": {"publicaciones": 1, "metricas": 1, "fallidas": 0}},
  "publicaciones": [{
    "id": "yt:ejemplo",
    "plataforma": "youtube",
    "titulo": "Ejemplo de IA",
    "texto": "Descripción",
    "autor_hash": "hash-sin-nombre",
    "url": "https://www.youtube.com/watch?v=ejemplo",
    "publicada_en": "2026-10-16T12:00:00Z",
    "idioma": "es",
    "pais": "CO"
  }],
  "metricas": [{
    "publicacion_id": "yt:ejemplo",
    "capturada_en": "2026-10-17T06:00:00Z",
    "vistas": 12000,
    "likes": null,
    "comentarios": 0
  }]
}
```

## Configuración local

Primera instalación, desde la raíz:

```powershell
cd main_backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ../ai_service -e ".[test]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Si `.env` ya existe, actualiza las variables manualmente; no copies encima.
Se busca siempre en `main_backend`. Reinicia el proceso tras modificarlo.

```dotenv
COLLECTOR_MODE=http
COLLECTOR_URL=https://radar-recoleccion.onrender.com
COLLECTOR_TIMEOUT_SECONDS=30
COLLECTOR_SEARCH_TIMEOUT_SECONDS=150
COLLECTOR_POLL_INTERVAL_SECONDS=2
COLLECTOR_DEFAULT_DAYS=7
COLLECTOR_DEFAULT_COUNTRY=CO
AI_ANALYZE_URL=https://radar-ai-8xi7.onrender.com/analyze
AI_TIMEOUT_SECONDS=45
RESEARCH_TIMEOUT_SECONDS=210
CORS_ORIGINS=[]
```

`COLLECTOR_URL` es la URL BASE, no termina en `/busquedas`. No configurar token:
el cliente no envía `Authorization` ni `X-Token` al recolector. Elimina el antiguo
`COLLECTOR_TOKEN`. `COLLECTOR_MODE` solo admite `http`; `https` es un protocolo de
la URL, no un modo. `mock` ya no está disponible. La clave Groq permanece en IA.

Para usar IA local, configura `AI_ANALYZE_URL=http://127.0.0.1:8001/analyze` e inicia
ese servicio por separado. No se modificó su implementación.

Inicio del backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn radar_backend.main:app --host 127.0.0.1 --port 8000 --reload
```

## Mapeo de filtros

| `/research` | Recolector o procesamiento local |
|---|---|
| `filters.query` | `tema`; no se exige coincidencia literal en los títulos devueltos |
| `filters.platform` | `redes: ["youtube"]` |
| `filters.country` | `paises: [country]`; si falta, `COLLECTOR_DEFAULT_COUNTRY` |
| `filters.published_after` | Se calcula `dias` desde UTC actual, redondeando hacia arriba y añadiendo un día de margen; el corte exacto se aplica localmente |
| Sin `published_after` | `COLLECTOR_DEFAULT_DAYS`; por defecto siete días |
| `filters.published_before` | No tiene equivalente remoto: límite inclusivo local |
| `filters.language` | No tiene equivalente remoto: igualdad local con `idioma`; si es desconocido se excluye y se cuenta |
| `filters.sample_size` | No tiene equivalente remoto: máximo 1–10 videos enviados a IA, ordenados por vistas conocidas e ID |

El país del recolector es **región de búsqueda, no ubicación del autor**. Su código
de YouTube utiliza español como idioma de relevancia; no garantiza que los videos
estén en español. El filtro local de idioma puede dejar pocos o ningún resultado.

Una fecha final antigua sin fecha inicial no amplía la ventana de siete días:
podría devolver cero coincidencias. Para una ventana histórica indica ambas fechas.
Se rechaza un inicio futuro o de hace más de 36500 días antes de iniciar la tarea.
El margen temporal es aproximado; se presupone que los relojes están sincronizados.

`sample_size=1` no limita el trabajo remoto: el recolector consulta hasta 50 videos
por término/país y luego se selecciona localmente. Para una primera prueba usa un
solo tema, un país y `COLLECTOR_DEFAULT_DAYS=1`, omitiendo fechas de publicación.

## Normalización y respuesta

`collector_contract.py` une `publicaciones[].id` con `metricas[].publicacion_id`,
conservando `yt:`. Se usa **la fecha de cada métrica**, no la captura del metadato.
`titulo` → `title`, `texto` → `description`, `publicada_en` → `published_at`,
`vistas` → `views`, `likes` → `likes`, `comentarios` → `comments`.
`author` es `null`: nunca se inventa un nombre desde `autor_hash`.

Se conserva cero; ausentes o desconocidos quedan como `null`. No se convierten
booleanos, cadenas ni decimales en conteos. Registros inválidos, sin coincidencia
o con IDs duplicados se excluyen y reportan. Capturas distintas para un mismo ID
se consideran ambiguas y no se elige una arbitrariamente. Vistas desconocidas no
participan en la selección. No se truncan textos silenciosamente.

El frontend conserva los tres bloques:

- `analysis`: el contrato existente de IA, con ranking verificado, análisis,
  recomendaciones, referencias y limitaciones.
- `sources`: ID, título y URL de cada video enviado al servicio IA.
- `collection`: `mode: "http"`, `simulated: false`, filtros y reporte `preparation`.
  El reporte incluye `search_id`, `collector_parameters`, fechas por ID, exclusiones
  y selección. Así puede rastrearse la tarea del recolector.

El backend impone limitaciones sobre selección y ausencia de evidencia de crecimiento.
Si el recolector informa consultas parcialmente fallidas, también se comunica.
Referencias válidas y JSON correcto no garantizan que toda interpretación sea verdadera.

## Postman

1. GET `http://127.0.0.1:8000/health`: debe devolver estado ok y modo http. No
   consulta dependencias ni consume cuotas; no confirma que estén disponibles.
2. POST `http://127.0.0.1:8000/research`, Authorization **No Auth**.
3. Headers: `Content-Type: application/json`, `Accept: application/json`.
4. Body → raw → JSON:

```json
{
  "question": "¿Qué destaca en esta selección y qué contenido útil sobre IA podría producir 30X? Distingue observaciones de hipótesis.",
  "audience": "Líderes y equipos de Latinoamérica que aplican IA en su trabajo",
  "filters": {
    "query": "inteligencia artificial",
    "platform": "youtube",
    "country": "CO",
    "sample_size": 1
  }
}
```

5. Timeout de Postman: `240000` ms. Pulsa Send **una sola vez**; el backend crea
   la tarea y la consulta con pausas. No es streaming ni hay progreso de frontend.
6. Comprueba HTTP 200, `collection.simulated: false`, ID de búsqueda, un video en
   ranking/fuentes y referencias a ese ID. Revisa las limitaciones y el contenido
   editorial. Una sola captura no demuestra crecimiento reciente.

Si seleccionas `language: "es"`, se filtrará estrictamente y podrían faltar
coincidencias. `/docs` describe los campos y límites. Pregunta: máximo 1500;
audiencia: máximo 1000; tema: máximo 200 caracteres.

## Plazos y errores

Solo se hace **un POST de creación**, sin reintentos. La consulta GET se repite
exclusivamente mientras `estado == "en_curso"`, con pausas reales. Ni errores de
red ni respuestas ambiguas vuelven a crear la tarea. No hay fallback a datos ficticios.

- Timeout por petición: 30 s; plazo total de creación y consultas: 150 s.
- IA: 45 s; plazo total `/research`: 210 s. Mantén el total por encima del plazo
  de recolección más el de IA. El proxy de despliegue puede imponer su propio límite.
- El recolector puede seguir trabajando tras un timeout: no hay endpoint de cancelación.
- Si se conoce el ID, el error lo conserva para consultar GET `/busquedas/{id}`.
  Si el inicio quedó ambiguo sin ID, no repitas automáticamente `/research`.

| HTTP | Código / situación |
|---|---|
| 413 | `body_too_large`: más de 256 KiB de entrada |
| 422 | `invalid_input`, `invalid_collector_filters` o `no_usable_videos` |
| 502 | `collector_search_failed`, `collector_search_lost`, `collector_invalid_state`, `collector_invalid_response` o fallo de contrato IA |
| 503 | `collector_busy` (409 remoto), `collector_rate_limited`, `collector_unavailable` o IA no disponible |
| 504 | `collector_timeout`, `collector_search_timeout`, `research_timeout` o timeout IA |
| 502/503/504 | `collector_start_uncertain`: inicio no confirmado; **no repetir automáticamente** |

Formato estable: `{"error":{"code":"...","message":"...","details":[]}}`.
No se devuelven mensajes privados de proveedores ni se registran claves/cuerpos.
Respuestas de recolector limitadas a 2 MiB y 2000 publicaciones/métricas; IA a
512 KiB. No hay paginación automática; no se envía la colección completa a IA.

## Render

Conserva la conexión de IA que ya funciona. Para desplegar el backend principal:

- Root Directory vacío (necesita ambos paquetes del repositorio).
- Build: `pip install ./ai_service ./main_backend`.
- Start: `uvicorn radar_backend.main:app --host 0.0.0.0 --port $PORT`.
- Health Check: `/health`.
- Actualiza las variables de `.env.example` en Environment; no subas `.env`.
- Conserva `AI_ANALYZE_URL` apuntando a la IA desplegada y `AI_TIMEOUT_SECONDS=45`.
- Elimina cualquier `COLLECTOR_TOKEN` y reemplaza modo `mock`/`https` por `http`.
- Para navegador: `CORS_ORIGINS=["https://tu-frontend.example"]` sin barra final.

No se implementó autenticación de usuarios ni control por usuario de cuotas.
CORS no es autenticación. Las instancias gratuitas pueden tardar en despertar;
GET `/salud` del recolector y `/health` de IA permiten comprobar disponibilidad
sin iniciar búsquedas ni inferencias. No crees búsquedas para despertar servicios.

## Pruebas y comprobación real manual

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Las pruebas bloquean red externa y verifican creación/polling, plazos, POST único,
estados, búsquedas vacías/fallidas, normalización, filtros, ranking y referencias.
Incluyen una aplicación real de IA con la inferencia simulada. No necesitan claves.

La comprobación real manual es separada, consume cuotas y crea una búsqueda:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_live.py --ai-url https://radar-ai-8xi7.onrender.com/analyze --report examples\live_check_nuevo.json
```

Hace una sola solicitud al `/research` local mediante ASGI, con clientes HTTP reales
para recolector e IA, un día, un tema, un país y muestra de un video. Guarda primero
el ID y después el informe, sin claves ni cuerpos completos. No ejecutes de nuevo
para recuperar una tarea anterior; usa su ID. Rechaza sobrescribir informes.

La prueba del 17 de octubre de 2026 (hora de Colombia) quedó en
`examples/live_check_collector_2026-10-17.json`: HTTP 200, 49 publicaciones y métricas,
un video analizado, tres hallazgos y tres recomendaciones. Es evidencia de integración,
no una prueba de tendencias ni de acceso ilimitado a proveedores.
