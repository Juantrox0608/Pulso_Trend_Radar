# Microservicio IA de 30X RADAR

Para probar las exportaciones reales del equipo, consulta
[preparación y Postman con cinco videos](examples/REAL_DATA.md).

Recibe videos desde el JSON de cada solicitud, calcula el ranking con Python y pide
una interpretación real a Groq. No consulta YouTube, no descarga URLs y no usa base
de datos. Los ejemplos son ficticios. No mide crecimiento histórico ni viralidad global.

## 1. Preparar el entorno (PowerShell)

Desde la raíz del repositorio:

```powershell
cd ai_service
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

En el editor local completa `GROQ_API_KEY` con tu clave obtenida desde
[Groq Console](https://console.groq.com/keys). No la pegues en chats, ejemplos,
Postman ni archivos versionados. `.env` está excluido de Git. Si ya existe tu `.env`,
omite `Copy-Item` para conservarlo. No necesitas activar el entorno virtual.

Configuración inicial:

```dotenv
GROQ_API_KEY=tu_clave_solo_en_el_archivo_local
GROQ_MODEL=openai/gpt-oss-20b
GROQ_TIMEOUT_SECONDS=30
GROQ_MAX_COMPLETION_TOKENS=4096
```

El archivo `.env` se busca siempre dentro de `ai_service`, independientemente del
directorio de ejecución. Reinicia el servidor después de cambiarlo. `/health` funciona con la
clave vacía; `/analyze` devuelve 503 si falta configuración.

## 2. Iniciar

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Documentación interactiva: http://127.0.0.1:8001/docs

El servidor queda limitado a la máquina local. Esta fase no incluye autenticación
de clientes; cualquier exposición a una red requiere acordar su control de acceso.

## 3. Postman: comprobar disponibilidad

- Método: **GET**
- URL: `http://127.0.0.1:8001/health`
- Authorization: **No Auth**
- Sin cuerpo ni encabezados especiales.
- Respuesta: HTTP 200, `{"status":"ok"}`. No llama a Groq.

## 4. Postman: análisis real con datos ficticios

- Método: **POST**
- URL: `http://127.0.0.1:8001/analyze`
- Authorization: **No Auth**. La clave de Groq permanece en el servidor.
- Headers: `Content-Type: application/json` y `Accept: application/json`.
- Body → **raw** → **JSON**.
- Copia TODO el contenido de [`examples/analyze_request.json`](examples/analyze_request.json)
  y pégalo en Body. Ese archivo es el cuerpo completo, no envíes su ruta ni un campo `file`.
- Configura el timeout de Postman por encima de 30 segundos, por ejemplo 45.000 ms.
- Pulsa **Send**. Esta operación sí consume cuota real de tu cuenta Groq.

La muestra contiene cuatro videos inventados, dos empatados en 12.000 vistas,
uno con cero y uno con vistas desconocidas. Los enlaces son marcadores ficticios:
no es necesario abrirlos. Cambia las vistas de `test-video-c` a 50000 y vuelve a
enviar para comprobar que el ranking usa el cuerpo recibido.

Formato ilustrativo de respuesta (el texto del modelo varía):

```json
{
  "summary": "Demostración con cuatro publicaciones ficticias; dos comparten el mayor número de vistas conocidas.",
  "findings": [
    {
      "observation": "El título de test-video-a menciona automatizar reportes.",
      "hypothesis": "El enfoque práctico podría ser pertinente para equipos; no demuestra por qué obtuvo esas vistas.",
      "source_video_ids": ["test-video-a"]
    }
  ],
  "recommendations": [
    {
      "title": "Cómo evaluar un reporte generado con IA",
      "suggested_format": "Tutorial con ejemplo empresarial",
      "reason": "Ofrece a los equipos una aplicación concreta y una forma de comprobar resultados.",
      "source_video_ids": ["test-video-a"]
    }
  ],
  "limitations": [
    "El análisis se limita a los videos recibidos y sus metadatos.",
    "No se analizó el contenido audiovisual completo.",
    "No hay historial para establecer crecimiento ni referencia de desempeño del canal.",
    "Las hipótesis no demuestran causalidad.",
    "Los videos sin visualizaciones conocidas fueron excluidos del ranking.",
    "Datos ficticios: no constituyen evidencia de mercado."
  ],
  "ranking": [
    {"video_id":"test-video-a","position":1,"metric":"views","value":12000},
    {"video_id":"test-video-b","position":1,"metric":"views","value":12000},
    {"video_id":"test-video-c","position":3,"metric":"views","value":0}
  ],
  "ranking_method": "views_desc",
  "unranked_video_ids": ["test-video-d"],
  "analysis_mode": "groq"
}
```

## Contrato

- `question`: obligatorio, 1–2000 caracteres; `audience`: obligatorio, 1–1000.
- `videos`: 1–30 elementos, IDs únicos; cuerpo máximo de 256 KiB, también para envíos por fragmentos.
- Cada video requiere `id` (1–128), `title` (1–500), `url` HTTPS de YouTube,
  `published_at`, `metrics_collected_at`, `views`, `likes` y `comments`.
- Fechas ISO 8601 con zona horaria. La recolección no puede preceder a la publicación.
- Métricas: enteros no negativos o `null`, sin conversión desde texto, decimales o booleanos.
  Un campo de métrica omitido es un error; un valor desconocido se envía como `null`.
- Opcionales: `description` (hasta 5000 caracteres), `author` (hasta 300); por defecto `null`.
- Campos desconocidos se rechazan. Una lista vacía produce 422.
- Ranking: vistas conocidas descendentes; empate comparte posición (`1,1,3`),
  orden secundario por ID ascendente. Cero sí participa; `null` se excluye.
- Sin vistas conocidas se devuelve ranking vacío y limitaciones; Groq puede interpretar
  metadatos, pero no comparar desempeño. Un único video se admite con advertencia.
- Python produce el ranking, exclusiones y limitaciones obligatorias. El modelo solo
  produce resumen, hallazgos, recomendaciones y limitaciones adicionales.
- Cada hallazgo y recomendación debe citar IDs recibidos. El servicio rechaza referencias
  inexistentes. La validación del esquema no garantiza la veracidad de cada interpretación.
- Los enlaces originales se resuelven usando los videos de entrada, nunca mediante el modelo.

## Errores

```json
{"error":{"code":"provider_rate_limited","message":"Groq alcanzó un límite de uso; intenta más tarde.","details":[]}}
```

| HTTP | Código | Acción |
|---|---|---|
| 413 | `body_too_large` | Reducir el cuerpo a 256 KiB o menos |
| 422 | `invalid_input` | Corregir tipos, fechas, IDs o límites; `details` indica ubicación y tipo |
| 502 | `invalid_provider_response` | JSON/esquema inválido, respuesta incompleta o truncada |
| 502 | `invalid_source_reference` | El modelo citó un ID ajeno a la solicitud |
| 502 | `provider_rejected_request` | Revisar modelo, formato y presupuesto de contexto |
| 503 | `provider_configuration` | Completar clave local o elegir un modelo verificado |
| 503 | `provider_authentication` | Revisar clave y permisos en Groq Console |
| 503 | `provider_rate_limited` | Esperar y revisar límites/cuotas de la cuenta |
| 503 | `provider_unavailable` | Fallo de conexión o indisponibilidad de Groq |
| 504 | `provider_timeout` | Plazo total agotado |

No hay respuestas simuladas de respaldo. Nunca se transforma un fallo de Groq en
HTTP 200. No se registran cuerpos, credenciales ni mensajes internos del proveedor.
Timeout total de 30 segundos por defecto; máximo dos intentos ante errores de conexión
o HTTP 500/502/503/504, con 250 ms de espera. No se reintentan 429, autenticación,
salidas inválidas ni timeout. Un reintento puede volver a consumir cuota.

Los límites HTTP y de caracteres protegen la entrada, pero no garantizan que cualquier
solicitud quepa en la cuota de tokens de tu cuenta. Empieza con la muestra pequeña;
no se truncan ni descartan videos silenciosamente.

## Pruebas sin Groq real

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Usan proveedores falsos y `httpx.MockTransport`: no necesitan `.env` ni clave,
no hacen solicitudes reales ni consumen cuotas. Cubren ranking, validación,
endpoint, referencias, JSON mal formado, truncamiento, autenticación, cuotas,
plazo total y reintentos limitados. La prueba real queda a cargo de Postman.

## Archivos y conceptos

| Archivo | Responsabilidad / concepto |
|---|---|
| `app/main.py`, `routes.py` | Aplicación, ciclo de vida, HTTP, límites y errores |
| `app/schemas.py` | Contratos Pydantic y validación |
| `app/ranking.py` | Función determinista, sin IA ni red |
| `app/analysis.py` | Flujo y validación de referencias |
| `app/groq_client.py` | HTTP asíncrono, formato, plazo y errores de Groq |
| `app/prompts.py` | Instrucciones y límites del análisis |
| `app/config.py` | Configuración local y secreto enmascarado |
| `tests/` | Comportamiento verificable sin red |

Para el equipo: compartir `/docs`, el JSON de ejemplo y esta tabla de errores.
La API principal deberá enviar este mismo contrato, sin conocer el cliente Groq.

## Decisiones verificadas con documentación oficial (17 de octubre de 2026)

- [Structured Outputs](https://console.groq.com/docs/structured-outputs):
  `openai/gpt-oss-20b` y `openai/gpt-oss-120b` admiten `json_schema` con `strict: true`.
  Se exige `additionalProperties: false` y todos los campos requeridos; los campos
  anulables siguen siendo requeridos. El cliente restringe la selección a estos dos
  modelos verificados. Para añadir otro, revisar primero su compatibilidad.
- [API reference](https://console.groq.com/docs/api-reference): se usa
  `POST /openai/v1/chat/completions`, `messages`, `response_format` y
  `max_completion_tokens`. Sin streaming ni herramientas.
- [Rate limits](https://console.groq.com/docs/rate-limits): los límites dependen
  de la cuenta/modelo; no se promete acceso gratuito ilimitado ni precios concretos.

El nombre del modelo contiene `openai/`, pero la inferencia y autenticación de este
servicio se realizan en Groq. No se hizo una llamada real al desarrollar las pruebas.
