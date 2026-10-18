# Prueba con exportaciones reales del equipo — 17 de octubre de 2026

## Resultado de la preparación

- 1010 metadatos, 1009 registros de estadísticas, 1009 uniones válidas por ID completo.
- Sin duplicados, registros unidos inválidos ni campos de métricas omitidos.
- Sin estadísticas: `yt:eCTMxfst7wE`; excluido de la selección y registrado en el informe.
- Captura de estadísticas: `2026-10-17T06:42:53.022937+00:00`. No se utiliza
  `capturada_en` de los metadatos para fechar las métricas.
- Muestra: cinco videos con más vistas conocidas entre los registros válidos unidos,
  con orden secundario por ID. No hay filtro editorial de pertinencia ni idioma.
- Algunos títulos corresponden a política o entretenimiento; no se debe asumir
  que toda la recolección es pertinente para IA o para la audiencia de 30X.
- `autor_hash` no se convierte en nombre: `author` queda `null`.
- Una sola captura no permite afirmar crecimiento reciente.

| Posición | ID | Vistas |
|---|---|---|
| 1 | `yt:qDzg-xvkeXw` | 2355931 |
| 2 | `yt:9-o5oNgJzJE` | 2169167 |
| 3 | `yt:wwl_9yI2RGU` | 1690488 |
| 4 | `yt:go6yxgk6odU` | 1571277 |
| 5 | `yt:NsTCeiiuL3g` | 1191979 |

Archivos generados:

- `analyze_real_top5_2026-10-17.json`: cuerpo completo para `/analyze`.
- `preparation_report_2026-10-17.json`: coincidencias, exclusiones, ranking esperado,
  campos omitidos y SHA-256 de los originales para trazabilidad.

## Transformación

| Exportación | Contrato `/analyze` |
|---|---|
| `id`, incluida la parte `yt:` | `id` |
| `titulo` | `title` |
| `texto` | `description` |
| `url` | `url` |
| `publicada_en` | `published_at` |
| `capturada_en` del archivo de estadísticas | `metrics_collected_at` |
| `stats[id].viewCount` | `views` |
| `stats[id].likeCount` | `likes` |
| `stats[id].commentCount` | `comments` |
| Solo `autor_hash` disponible | `author: null` |

Los campos que el contrato no admite (hashtags, duración, consulta, país, etc.) no
se envían al modelo y aparecen enumerados en el informe. Las claves de métricas
ausentes se convierten en `null` con aviso; un cero se conserva. Tipos incorrectos,
fechas inválidas, textos demasiado largos o plataformas incompatibles se reportan
y excluyen, sin truncar ni convertir silenciosamente. IDs duplicados se excluyen;
claves JSON duplicadas o una fecha global de captura inválida detienen el script.

## Ejecutar nuevamente el preparador

Desde `ai_service`, usa nombres de salida nuevos, pues el script rechaza sobrescribir
archivos existentes y nunca permite usar los originales como destino:

```powershell
.\.venv\Scripts\python.exe -m app.prepare_request --metadata "C:\Users\Usuario\Downloads\youtube_2026-10-17.json" --statistics "C:\Users\Usuario\Downloads\youtube_stats_2026-10-17.json" --output examples\analyze_real_top5_repeat.json --report examples\preparation_report_repeat.json --limit 5
```

El script no carga `.env`, no hace llamadas externas y no ejecuta inferencias.
Si no hay videos válidos con vistas conocidas, escribe el informe, sale con código
2 y no crea una solicitud vacía. El endpoint no se ha acoplado a estos archivos.

## Postman: prueba real con Groq

1. Desde `ai_service`, inicia el servidor con tu `.env` local ya configurado:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
   ```

2. `GET http://127.0.0.1:8001/health`, sin autorización ni cuerpo: debe devolver
   `200` y `{"status":"ok"}`. No comprueba Groq ni consume cuota.
3. Crea `POST http://127.0.0.1:8001/analyze`.
4. Authorization: **No Auth**. Nunca pegues la clave Groq en Postman.
5. Headers: `Content-Type: application/json`, `Accept: application/json`.
6. Body → **raw** → **JSON**. Pega el contenido completo de
   `analyze_real_top5_2026-10-17.json`; no pegues los originales ni el informe.
7. Configura timeout de Postman de 45000 ms y pulsa **Send**. Se enviarán solo
   cinco videos a Groq. Esta operación consume cuota; no se ha ejecutado durante
   la preparación ni en las pruebas automáticas.
8. Comprueba HTTP 200 y:
   - `ranking`: los cinco IDs y valores de la tabla, en el mismo orden.
   - `summary`, `findings` y `recommendations`: análisis con pertinencia para 30X;
     el texto varía según el modelo y puede reconocer insuficiencia o irrelevancia.
   - `source_video_ids`: únicamente IDs presentes en los cinco videos enviados.
   - `limitations`: metadatos únicamente, sin contenido audiovisual ni historial.
     Revisar además que el análisis reconozca la selección por vistas acumuladas.
   - `analysis_mode: "groq"` y `unranked_video_ids: []`.
   - Ninguna afirmación de crecimiento reciente, causalidad demostrada o cobertura
     de todo YouTube. Las referencias válidas no garantizan la verdad del texto.

Puedes añadir esta comprobación en Scripts → Post-response de Postman:

```javascript
pm.test("HTTP 200", () => pm.response.to.have.status(200));
if (pm.response.code === 200) {
  const input = JSON.parse(pm.request.body.raw);
  const result = pm.response.json();
  const ids = new Set(input.videos.map(v => v.id));
  const ordered = input.videos.filter(v => v.views !== null)
    .sort((a, b) => b.views - a.views || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  let position = 0;
  const expected = ordered.map((v, index) => {
    if (index === 0 || v.views !== ordered[index - 1].views) position = index + 1;
    return {video_id: v.id, position, metric: "views", value: v.views};
  });
  pm.test("Ranking calculado", () => pm.expect(result.ranking).to.deep.equal(expected));
  pm.test("Análisis y limitaciones presentes", () => {
    pm.expect(result.summary).to.be.a("string").and.not.empty;
    pm.expect(result.findings).to.be.an("array");
    pm.expect(result.recommendations).to.be.an("array");
    pm.expect(result.limitations).to.be.an("array").and.not.empty;
    pm.expect(result.analysis_mode).to.equal("groq");
  });
  pm.test("Referencias recibidas", () => {
    [...result.findings, ...result.recommendations].forEach(item => {
      pm.expect(item.source_video_ids).to.be.an("array").and.not.empty;
      item.source_video_ids.forEach(id => pm.expect(ids.has(id)).to.equal(true));
    });
  });
}
```

Si recibes 503 `provider_rate_limited`, revisa los límites de tu cuenta y espera
antes de repetir. Una muestra de cinco limita el volumen, pero sus descripciones y
el presupuesto de salida también consumen tokens. Otros errores están documentados
en `../README.md`; nunca deben sustituirse por un análisis inventado.

## Qué falta para los endpoints desplegados del equipo

- Acordar URLs, autenticación, esquema/versiones, paginación y forma de obtener
  una captura coherente de metadatos y métricas.
- La API principal deberá unir/normalizar/seleccionar datos antes de invocar
  `/analyze`. La función de preparación sirve como referencia; las rutas HTTP
  seguirán recibiendo JSON, sin leer archivos de Downloads.
- Acordar selección editorial (tema, idioma, pertinencia) y dónde se aplica.
- Acordar timeout total, manejo de errores y control de cuota/concurrencia.
- Probar el recorrido real recolector → API principal → IA con referencias
  correctas y manejo de registros sin estadísticas.
- Si se pide crecimiento, obtener mediciones en distintos momentos y diseñar
  el cálculo; esta captura por sí sola no lo proporciona.
