# Guía de integración del frontend — 30X RADAR

## Qué API consumir

Usa como base `https://tred-radar.onrender.com`. El formulario llama a
**POST `/research`** y muestra su respuesta. No necesita consultar directamente
al recolector ni a IA. No necesita claves, sesiones, base de datos ni un GET posterior.
Para desarrollo local: `http://127.0.0.1:8000` con el backend iniciado.

La referencia completa está en [README_ENDPOINTS.md](README_ENDPOINTS.md) y el
contrato desplegado en `https://tred-radar.onrender.com/docs`.

Estado comprobado en esta auditoría: YouTube pasó el flujo completo; LinkedIn
también con una ventana explícita de 30 días (la ventana predeterminada no encontró
publicaciones dentro de fecha). TikTok sigue sin datos por fallo de captura del
recolector: la UI debe mostrar ese estado, sin anunciarlo como integración exitosa.
El formato está implementado y probado localmente para las tres plataformas.

## Formulario y solicitud

Campos de UI recomendados:

- Pregunta: obligatoria, máximo 1500 caracteres.
- Audiencia: obligatoria, máximo 1000.
- Tema/búsqueda: obligatorio, máximo 200; una frase o hasta cinco términos por comas.
- Plataforma: youtube, linkedin o tiktok; **una por petición**.
- Tamaño de muestra: 1–10, empezar con 1; predeterminado del servidor 5.
- Opcionales: idioma, país, fecha inicial y fecha final. Fechas con zona horaria.

Ejemplo que puede enviarse sin cambiar nombres:

```json
{
  "question": "¿Qué enfoques aparecen y qué contenido útil sobre IA podría producir 30X? No afirmes crecimiento reciente.",
  "audience": "Líderes y equipos de Latinoamérica que aplican IA en su trabajo",
  "filters": {
    "query": "inteligencia artificial",
    "platform": "youtube",
    "country": "CO",
    "sample_size": 1
  }
}
```

Para LinkedIn cambia `platform` a `linkedin` y omite país salvo que quieras
conservarlo como preferencia visible: el recolector no aplica país a esa red.
Lo mismo ocurre con TikTok. Un idioma explícito descarta publicaciones de idioma
desconocido; omitirlo permite recibir más publicaciones.

En la auditoría de LinkedIn, la ventana predeterminada devolvió nueve publicaciones
fuera de fecha y ninguna utilizable. Eso es ausencia de coincidencias, no un fallo
de conexión. Para ampliar explícitamente a 30 días desde la UI puedes enviar:

```javascript
filters.published_after = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
```

No amplíes fechas silenciosamente: muestra al usuario qué ventana se está consultando.

`sample_size` limita lo enviado a IA, no el trabajo del recolector. No dispares
tres investigaciones simultáneas para llenar pestañas: el recolector admite una
búsqueda concurrente y podría responder ocupado.

## Ejemplo de cliente JavaScript

La URL es configuración pública. Puedes moverla a la variable de entorno pública
que use tu frontend; nunca incluyas `GROQ_API_KEY` ni credenciales del recolector.

```javascript
const API_BASE = "https://tred-radar.onrender.com";
let researchInFlight = false;

export class ApiError extends Error {
  constructor(message, status, code, details = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export async function investigate(input, { signal } = {}) {
  if (researchInFlight) {
    throw new ApiError("Ya hay una investigación en curso.", 0, "request_in_progress");
  }
  researchInFlight = true;
  try {
    const response = await fetch(`${API_BASE}/research`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "omit",
      body: JSON.stringify(input),
      signal
    });

    // Un proxy puede devolver HTML, no el formato de errores del backend.
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      throw new ApiError(
        body?.error?.message ?? `El servidor respondió HTTP ${response.status}.`,
        response.status,
        body?.error?.code ?? "unexpected_server_response",
        body?.error?.details ?? []
      );
    }
    if (!body?.analysis || !Array.isArray(body.sources) || !Array.isArray(body.metrics)) {
      throw new ApiError("La respuesta no tiene el formato esperado.", response.status, "invalid_response");
    }
    return body;
  } finally {
    researchInFlight = false;
  }
}
```

Uso desde el controlador del formulario (adaptar al framework):

```javascript
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 270_000);
try {
  // Activar estado loading y deshabilitar Enviar.
  const result = await investigate(formValues, { signal: controller.signal });
  // Guardar result en el estado de UI y renderizar sus cuatro bloques.
} catch (error) {
  if (error.name === "AbortError") {
    // Mostrar: "Se dejó de esperar; la investigación podría seguir activa."
    // No reenviar automáticamente.
  } else if (error instanceof ApiError) {
    // Mostrar mensaje y un diagnóstico de soporte con code y details.
  } else {
    // Error de red o CORS: consultar consola del navegador y configuración.
  }
} finally {
  clearTimeout(timer);
  // Desactivar loading. Tras timeout, pedir revisión antes de otra búsqueda.
}
```

El bloqueo del ejemplo evita duplicados en ese módulo/pestaña, no entre usuarios
o pestañas. Cancelar fetch no garantiza cancelar la búsqueda del recolector.
El código no debe reintentar POST automáticamente, ni siquiera tras un timeout.

## Qué mostrar con una respuesta 200

| Bloque | Uso en pantalla |
|---|---|
| `analysis.summary` | Resumen editorial |
| `analysis.findings` | Observación separada de hipótesis, con enlaces a evidencia |
| `analysis.recommendations` | Título, formato y justificación de cada propuesta |
| `analysis.ranking` | Posición por vistas acumuladas dentro de la muestra |
| `analysis.limitations` | Limitaciones siempre visibles |
| `sources` | ID, plataforma, título nullable y URL original |
| `metrics` | Vistas, likes, comentarios, compartidos y fecha de captura |
| `collection` | Procedencia, marca de simulación, filtros y diagnóstico opcional |

No asumas que la posición de `metrics[i]` corresponde al hallazgo `findings[i]`.
Une siempre por ID:

```javascript
const sourceById = new Map(result.sources.map(source => [source.id, source]));
const metricById = new Map(result.metrics.map(metric => [metric.id, metric]));
const rows = result.sources.map(source => ({
  ...source,
  metrics: metricById.get(source.id) ?? null
}));
const numberFormat = new Intl.NumberFormat("es-CO");
const displayMetric = value => value == null ? "No disponible" : numberFormat.format(value);

// Evidencia de un hallazgo:
const evidence = result.analysis.findings[0]?.source_video_ids
  .map(id => sourceById.get(id))
  .filter(Boolean) ?? [];
```

- `0` debe mostrarse como cero. `null` debe mostrarse como «No disponible».
  No usar `value || 0` ni reemplazar desconocidos por cero.
- `title: null` no es un fallo. Usa una etiqueta visual como «Publicación sin título disponible».
- `ranking: []` puede ser correcto, sobre todo en LinkedIn sin vistas. Mostrar
  «No hay vistas conocidas para ordenar esta muestra», conservando análisis y métricas.
- `sample_size: 3` puede devolver una o dos publicaciones si no hay más utilizables.
- Posiciones empatadas pueden ser `1,1,3`; no recalcularlas según el índice del array.
- `likes` no equivale necesariamente al total de reacciones; `shares` depende de
  los compartidos/republicaciones que la fuente permita obtener.
- `analysis_mode: "groq"` identifica al proveedor, no que los datos sean reales.
  La procedencia se indica en `collection.simulated`.
- Hallazgos y recomendaciones pueden estar vacíos. No rellenarlos con contenido inventado.
- Renderiza textos de fuentes y del modelo como texto, no como HTML sin sanitizar.
  En enlaces externos usa `target="_blank"` con `rel="noopener noreferrer"`.

## Estados de la interfaz

1. **Inicial:** formulario listo, sin resultados inventados.
2. **Cargando:** «Recolectando publicaciones y preparando el análisis». No hay
   progreso por etapa expuesto al frontend; no mostrar porcentajes ficticios.
3. **Éxito:** mostrar resumen, métricas, ranking disponible, evidencia y limitaciones.
4. **Sin resultados:** explicar que no hubo publicaciones utilizables para esos filtros.
5. **Dependencia fallida:** diferenciar captura fallida, servicio ocupado, cuota o timeout.
6. **Red/CORS:** mostrar un mensaje de conexión; un fetch rechazado no ofrece siempre status HTTP.

Los servicios gratuitos pueden tardar al despertar; un indicador de carga es
necesario. GET `/health` sirve para disponibilidad, no para comprobar Groq ni
para mantener un servicio artificialmente activo mediante sondeos permanentes.

## Errores que debe manejar el frontend

Formato común:

```json
{
  "error": {
    "code": "collector_capture_failed",
    "message": "El recolector no pudo capturar publicaciones de esta plataforma.",
    "details": [{
      "service": "collector",
      "platform": "tiktok",
      "search_id": "0123456789abcdef0123456789abcdef",
      "ai_called": false,
      "reason": "capture_failed_or_stopped"
    }]
  }
}
```

Ejemplo abreviado; el mensaje y los detalles reales pueden incluir más campos.

| Código / estado | Comportamiento de UI |
|---|---|
| `invalid_input`, `invalid_collector_filters` / 422 | Corregir formulario; `details[].location` localiza campos si existe |
| `no_usable_videos` / 422 | Mostrar ausencia de publicaciones utilizables, sin inventar análisis |
| `collector_capture_failed` / 502 | Mostrar problema de captura de esa red; conservar ID para soporte |
| `collector_busy` / 503 | Informar búsqueda en curso; no repetir automáticamente |
| `collector_start_uncertain` | Advertir inicio no confirmado; no crear otra tarea automáticamente |
| `ai_provider_rate_limited`, `ai_rate_limited` / 503 | Informar límite de uso; no crear otra recolección por reintento automático |
| Otros 502/503 | Mensaje de dependencia y diagnóstico seguro; conservar error para soporte |
| 504 o aborto local | Informar tiempo agotado y posible tarea activa; no prometer cancelación |

`details` es una lista de objetos extensibles y puede estar vacía. No depende de
ella para decidir si HTTP fue éxito: usa `response.ok`. Nunca trates un error como
un análisis exitoso ni muestres resultados anteriores como si fueran nuevos.

## CORS y despliegue del frontend

En Environment de **`tred-radar`**, el backend debe permitir el origen exacto del
frontend, sin rutas ni barra final. Ejemplo:

```dotenv
CORS_ORIGINS=["https://tu-frontend.example","http://localhost:5173"]
```

El responsable del backend debe reemplazar el dominio por el real y aplicar el
despliegue. Postman no aplica CORS: una prueba exitosa allí no confirma integración
desde navegador. El navegador puede enviar OPTIONS antes del POST; el backend
permite GET/POST y Content-Type a los orígenes configurados. No uses `mode: "no-cors"`.

No configures AI_ANALYZE_URL ni claves de Groq en el frontend. No hay cookies ni
Bearer de usuario implementados en esta fase. CORS no protege la cuota contra
clientes externos; el control de acceso deberá definirse antes de una apertura amplia.

## Pruebas de aceptación del frontend

- YouTube y LinkedIn: una solicitud por vez, muestra 1; renderizar respuesta real.
- Comprobar visualmente cero frente a null, título nulo y ranking vacío sin error.
- Verificar enlaces de fuentes y referencias por ID, no por posición.
- Entrada inválida: enviar tamaño de muestra 11 y mostrar 422 sin quedarse cargando.
- Carga: deshabilitar doble envío; limpiar loading tanto en éxito como en error.
- TikTok: mostrar el diagnóstico si falla la captura; no presentar el éxito como confirmado.
- Navegador desplegado: confirmar OPTIONS/CORS con su dominio real.
- No evaluar tendencias o interacción alta/baja sin referencia; mostrar hipótesis
  como hipótesis. La salida del modelo requiere criterio editorial.

Los resultados de auditoría están en [el informe](endpoint_audit_2026-10-18.json).
Una prueba puntual no garantiza que los proveedores externos siempre entreguen datos.
