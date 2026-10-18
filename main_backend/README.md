# Backend principal de 30X RADAR

Orquesta frontend → recolector → preparación → microservicio IA → frontend.
No consulta directamente YouTube ni Groq. No usa base de datos. La clave Groq
permanece exclusivamente en `ai_service/.env`.

El recolector todavía no tiene un contrato HTTP acordado. Por defecto se ejecuta
`COLLECTOR_MODE=mock`, con cuatro publicaciones FICTICIAS, métricas inventadas y
fecha fija. **El análisis se solicita al servicio IA real por HTTP**; por tanto,
al ejecutar `/research` normalmente sí se consume cuota Groq. Las pruebas no
realizan llamadas externas. El modo simulado no se activa desde el cuerpo HTTP.

## Preparar y ejecutar (PowerShell)

Primera vez, desde la raíz del repositorio:

```powershell
cd main_backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ../ai_service -e ".[test]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Ambos proyectos se instalan desde sus carpetas locales. Se comparten los esquemas
Pydantic, ranking y preparador de `ai_service` como dependencia Python local;
no se duplica el contrato y no se llama al análisis de IA dentro del proceso.
Para instalar este backend debes tener ambas carpetas del repositorio. A futuro,
el contrato compartido puede extraerse a un paquete independiente.

Terminal 1, desde `ai_service`, con su clave local ya configurada:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Terminal 2, desde `main_backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn radar_backend.main:app --host 127.0.0.1 --port 8000 --reload
```

El `.env` del backend principal se busca siempre en `main_backend`. Reinicia
el proceso después de cambiarlo. No copies la clave Groq a esta carpeta.

## Postman

### Salud

- Método: GET.
- URL: `http://127.0.0.1:8000/health`.
- Authorization: No Auth. Sin cuerpo.
- Respuesta: `{"status":"ok","service":"main_backend","collector_mode":"mock"}`.
- No llama al recolector, al servicio IA ni a Groq. No es prueba de disponibilidad
  de las dependencias.

### Investigar

- Método: POST.
- URL: `http://127.0.0.1:8000/research`.
- Authorization: No Auth.
- Headers: `Content-Type: application/json`, `Accept: application/json`.
- Body → raw → JSON: pega todo `examples/research_request.json`:

```json
{
  "question": "¿Qué videos destacan en la selección y qué contenido sobre IA podría producir 30X para esta audiencia?",
  "audience": "Líderes y equipos de Latinoamérica que están aprendiendo a aplicar IA en su trabajo",
  "filters": {
    "query": "IA",
    "platform": "youtube",
    "language": "es",
    "country": "CO",
    "published_after": "2026-10-01T00:00:00Z",
    "published_before": "2026-10-17T23:59:59Z",
    "sample_size": 3
  }
}
```

- Timeout de Postman: 75000 ms. Plazo total del backend: 60 segundos por defecto;
  recolector: 10; servicio IA: 45. No hay reintentos HTTP en el backend principal.
- Send. Espera HTTP 200, con este envoltorio:

```text
{
  "analysis": {ranking, summary, findings, recommendations, limitations, ...},
  "sources": [{"id": "yt:mock-1", "title": "[FICTICIO] ...", "url": "https://..."}, ...],
  "collection": {
    "mode": "mock",
    "simulated": true,
    "filters": {...},
    "preparation": {...}
  }
}
```

El bloque anterior ilustra la forma, no es JSON para pegar. `analysis` conserva
el contrato de `/analyze`; su `analysis_mode: "groq"` describe el proveedor,
mientras `collection.simulated: true` señala que las publicaciones son ficticias.
Se añade una limitación obligatoria de simulación incluso si el modelo la omite.
`sources` permite resolver los IDs sin pedirle al modelo que invente URLs.

Pruebas manuales adicionales:

1. Cambia `query` a `reuniones`: se selecciona solo `yt:mock-3`, con cero vistas.
2. Cambia `query` a un texto inexistente: 422 `no_usable_videos`, sin llamada a IA.
3. Cambia `sample_size` a 11: 422 `invalid_input`, sin llamar a las dependencias.
4. Detén el servicio IA y repite una búsqueda válida: 503 `ai_unavailable`.

Documentación: `http://127.0.0.1:8000/docs`; contrato OpenAPI en `/openapi.json`.

## Filtros y preparación

- `question`: texto no vacío, máximo 1500 caracteres; `audience`: máximo 1000.
- `filters.query`: obligatorio, máximo 200; `platform`: solo `youtube`.
- `language`, `country`, `published_after`, `published_before`: opcionales.
  Idioma de dos letras minúsculas; país de dos letras mayúsculas; fechas con zona.
- `sample_size`: entero 1–10, por defecto 5. Es el máximo enviado a IA.
- El adaptador local aplica búsqueda literal sin distinguir mayúsculas sobre
  título + descripción, idioma/país por igualdad y fechas inclusivas. No es una
  búsqueda semántica. Estas reglas se aplican también al resultado HTTP.
- Si faltan idioma o país y se solicitó ese filtro, el registro se excluye y se
  cuenta en `missing_filter_fields_records`. El país se trata como campo del
  recolector; no se deduce la nacionalidad ni ubicación del autor.
- Se unen metadatos y métricas por ID completo; no se elimina `yt:`. Se excluyen
  duplicados, registros inválidos y registros sin estadísticas. Se preserva cero,
  se usa `null` para desconocidos y `author: null` si solo hay `autor_hash`.
- Tras filtrar, se seleccionan las mayores vistas conocidas. Cero participa;
  vistas desconocidas no participan en esta selección. Empates por ID.
- El ranking final lo produce IA mediante su módulo Python de ranking. El backend
  principal lo recalcula solo para verificar el contrato y rechaza diferencias.
- La pregunta original se conserva y se añade contexto sobre selección, muestra
  y ausencia de historial. No se afirma crecimiento reciente.
- Las exclusiones del recolector quedan en `collection.preparation` con índices
  referidos al orden original. No se envían a Groq todos los registros recibidos.
- Entrada máxima 256 KiB; respuesta del recolector 2 MiB y hasta 2000 metadatos;
  respuesta IA 512 KiB. No hay paginación automática todavía.

## Contrato HTTP provisional del recolector

**Esto es una interfaz propuesta, no una afirmación sobre el endpoint existente
de tu compañero.** Cuando entregue su contrato, adapta `CollectorClient.collect`
y el mapeo de preparación si hace falta; mantén `/research` y `/analyze` estables.

`COLLECTOR_MODE=http`: envía POST a la URL exacta `COLLECTOR_URL`, sin añadir rutas.
Cuerpo: `{"filters": {...}}` con los filtros anteriores, omitiendo valores nulos.
Si `COLLECTOR_TOKEN` está configurado, envía `Authorization: Bearer ...`.

Respuesta HTTP 200 propuesta:

```json
{
  "metadata": [
    {
      "id": "yt:abc123",
      "plataforma": "youtube",
      "titulo": "Ejemplo de IA",
      "texto": "Descripción disponible",
      "autor_hash": "hash-sin-nombre",
      "url": "https://www.youtube.com/watch?v=abc123",
      "publicada_en": "2026-10-10T12:00:00Z",
      "idioma": "es",
      "pais": "CO"
    }
  ],
  "statistics": {
    "capturada_en": "2026-10-17T06:00:00Z",
    "stats": {
      "yt:abc123": {"viewCount": 12000, "likeCount": null, "commentCount": 0}
    }
  }
}
```

No cambies a modo HTTP hasta conocer el contrato. Si falta URL o falla el recolector,
se devuelve error: **no se reemplaza silenciosamente por datos ficticios**.
Las URLs se configuran en el servidor; el frontend no puede elegir servidores externos.

Pide al compañero:

1. URL base y ruta, método GET/POST y parámetros exactos.
2. Autenticación y entrega del secreto fuera del chat/código.
3. Respuestas de ejemplo, campos/tipos, IDs con prefijo y valores desconocidos.
4. Si metadatos y estadísticas vienen juntos o en endpoints distintos; cómo se
   identifica una captura coherente y cómo se obtienen las métricas por IDs.
5. Significado real de idioma/país, filtros admitidos y orden de resultados.
6. Paginación, tamaños máximos, cuotas, tiempos y errores esperados.

## Errores y conexión del frontend

Formato: `{"error":{"code":"ai_unavailable","message":"...","details":[]}}`.

| HTTP | Situaciones |
|---|---|
| 413 | Entrada demasiado grande |
| 422 | Entrada inválida, filtros sin resultados o ninguna vista conocida utilizable |
| 502 | JSON/contrato externo inválido, referencias o ranking incorrectos, solicitud rechazada |
| 503 | Conexión, configuración, autenticación o cuotas de una dependencia |
| 504 | Plazo del recolector, IA o flujo total agotado |

Los códigos identifican `collector`, `ai` o `research`. No se reenvían cuerpos de
error internos, credenciales ni solicitudes completas a los logs. Para diagnosticar
un 503 del servicio IA, comprueba su `/analyze` directamente y su configuración local.

El frontend llama a `/research` y renderiza `analysis`, usando `sources` para enlaces.
Para un navegador, configura por ejemplo en `main_backend/.env`:

```dotenv
CORS_ORIGINS=["http://localhost:5173"]
```

Por defecto no se habilitan orígenes externos. CORS no es autenticación; esta fase
no incluye usuarios ni autenticación de clientes. El servidor se inicia solo en
loopback para pruebas locales. `127.0.0.1` no conecta máquinas o contenedores distintos.

## Archivos y pruebas

- `radar_backend/main.py`: rutas, ciclo de vida, CORS, límites y errores.
- `config.py`: entorno propio, plazos y direcciones de las dependencias.
- `schemas.py`: contratos del frontend y de la respuesta.
- `clients.py`: recolector simulado/HTTP y cliente HTTP de IA.
- `service.py`: filtrado, preparación, selección y comprobación del análisis.
- `examples/research_request.json`: solicitud para Postman.
- `tests/test_backend.py`: flujo, filtros, errores y comunicación HTTP simulada.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Las pruebas bloquean la red real. Cubren una ida y vuelta por la aplicación real
de IA con inferencia simulada. Las pruebas originales de IA se ejecutan aparte
desde `ai_service` y su entorno; no se modificó su implementación.

PostgreSQL, Docker y despliegue quedan para otra etapa.
