# Diagnóstico por componentes en Postman

No repetir `/research` hasta comprobar IA por separado. El mensaje antiguo
`ai_error` ocultaba varias respuestas del servicio IA. No demuestra que el JSON
del frontend sea incorrecto ni permite atribuirlo a una clave o cuota sin evidencia.

La corrección del backend principal conserva el envoltorio `error`, pero reconoce
códigos públicos del servicio IA y usa mensajes propios. `details` añade servicio,
HTTP remoto y, si está permitido, código remoto. No reenvía mensajes privados,
entradas inválidas, HTML ni cuerpos completos. Los errores desconocidos conservan
`ai_error`, ahora con `upstream_status` para poder diagnosticarlos.

## 1. Salud sin consumir cuotas

En Postman, con No Auth y sin cuerpo:

- GET `https://tred-radar.onrender.com/health` → 200, modo http.
- GET `https://radar-ai-8xi7.onrender.com/health` → 200, estado ok.
- GET `https://radar-recoleccion.onrender.com/salud` → 200, estado ok.

Esperar a que respondan, sobre todo si las instancias gratuitas estaban dormidas.
No iniciar búsquedas para despertarlas. Un health correcto no comprueba Groq.

## 2. Probar IA sin recolector

- POST `https://radar-ai-8xi7.onrender.com/analyze`.
- No Auth.
- Headers: `Content-Type: application/json`, `Accept: application/json`.
- Body → raw → JSON: contenido completo de `ai_probe_request.json` de esta carpeta.
- Timeout de Postman: 120000 ms para permitir despertar del servicio.
- Send una vez. Esta prueba sí consume una inferencia Groq con un video ficticio.

Si devuelve 200, revisar ranking de `yt:diagnostic-test` con 100 vistas, análisis,
referencias y limitaciones. Si falla, conservar estado HTTP y JSON exacto y detenerse:
no volver a consultar el recolector, porque no ayuda a resolver el fallo de IA.

| Código directo de IA | Interpretación |
|---|---|
| `provider_configuration` | Clave vacía o modelo fuera de los verificados; revisar el entorno del servicio IA |
| `provider_authentication` | Groq rechazó credenciales o permisos |
| `provider_rate_limited` | Cuota o límite de uso |
| `provider_rejected_request` | Groq rechazó la solicitud; revisar modelo/contexto, no aumentar parámetros a ciegas |
| `invalid_provider_response` | Salida truncada, formato o esquema inválido |
| `invalid_source_reference` | IDs inventados por el modelo |
| `provider_timeout` | Plazo de Groq agotado |

No compartir claves en capturas ni en el chat.

## 3. Publicar el diagnóstico del backend principal

La corrección está local; para que se refleje en Render hay que publicarla en la
rama conectada y desplegar ese commit. No se hicieron commits ni push automáticamente.
Conservar las variables y comandos actuales; esta corrección no cambia el contrato
de éxito ni la conexión con IA. Por ejemplo, un error ahora puede verse así:

```json
{
  "error": {
    "code": "ai_invalid_provider_response",
    "message": "La respuesta del modelo no cumple el formato esperado o está incompleta.",
    "details": [{
      "service": "ai",
      "upstream_status": 502,
      "upstream_code": "invalid_provider_response"
    }]
  }
}
```

Si aparece `ai_endpoint_not_found`, comprobar que `AI_ANALYZE_URL` termine en
`/analyze`; si es `ai_method_not_allowed`, comprobar que no apunte a `/health`.

## 4. Probar el flujo completo solo después de IA exitosa

- POST `https://tred-radar.onrender.com/research`.
- No Auth; Content-Type `application/json`.
- Timeout 270000 ms si el plazo de investigación en Render es 240 segundos.
- Body → raw → JSON:

```json
{
  "question": "¿Qué destaca en esta selección y qué idea útil sobre IA podría producir 30X? No afirmes crecimiento reciente.",
  "audience": "Líderes y equipos de Latinoamérica que aplican IA en su trabajo",
  "filters": {
    "query": "inteligencia artificial",
    "platform": "youtube",
    "country": "CO",
    "sample_size": 1
  }
}
```

Send una vez. Esperar ranking de un video, `sources`, análisis con referencias a
ese video, recomendaciones, limitaciones y `collection.simulated: false`.
Si falla IA con publicaciones reales, conservar el código de error: puede existir
un problema específico del volumen o de la respuesta del modelo que no aparezca
con el ejemplo corto. No repetir la recolección automáticamente.

## Verificaciones locales realizadas

Las pruebas bloquean la red y cubren éxito del flujo, fallos conocidos de IA,
errores desconocidos, respuestas inválidas, estados HTTP y eliminación de datos
privados del error. Se comprobó también una aplicación real de IA que falla con
proveedor simulado: el backend principal preserva el diagnóstico seguro.
