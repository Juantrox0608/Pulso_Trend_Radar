# YouTube, TikTok y LinkedIn

`POST /research` acepta `filters.platform` con `youtube`, `tiktok` o `linkedin`.
Se consulta **una plataforma por solicitud**. No se mezclan rankings de distintas
redes. El recolector conserva sus rutas, plazos y ausencia de token.

## Métricas comunes para el frontend

La respuesta conserva `analysis`, `sources`, `collection` y añade `metrics`,
con un registro por publicación seleccionada y enviada al servicio IA:

```json
{
  "metrics": [{
    "id": "li:1234567890123456789",
    "platform": "linkedin",
    "views": null,
    "likes": 12,
    "comments": 0,
    "shares": null,
    "metrics_collected_at": "2026-10-17T12:00:00Z"
  }]
}
```

Ejemplo ficticio de estructura, no evidencia real. El frontend debe mostrar `null`
como «No disponible» y cero como `0`; no usar `valor || 0`.

| Campo común | Campo del recolector | Significado |
|---|---|---|
| `views` | `vistas` | Vistas conocidas; no se sustituyen con impresiones |
| `likes` | `likes` | Likes reportados; no equivale automáticamente a todas las reacciones |
| `comments` | `comentarios` | Conteo disponible de comentarios |
| `shares` | `compartidos` | Compartidos/republicaciones reportados por la fuente |
| `metrics_collected_at` | `metricas[].capturada_en` | Fecha de esa observación |

El nombre común no garantiza definiciones ni cobertura idénticas entre redes.
No se calculan tasas sin denominador conocido ni puntajes con pesos arbitrarios.
`sources` añade `platform`. Su `title` puede ser `null` para publicaciones de texto.
No se inventa título ni nombre de autor a partir de texto o hashes.

## Selección y ranking

- Con vistas conocidas, se mantiene la selección por vistas descendentes e ID.
- Sin ninguna vista conocida, se selecciona por ID ascendente hasta `sample_size`.
  Es una muestra determinista de metadatos, no de desempeño.
- En ese caso IA devuelve `ranking: []` y los IDs en `unranked_video_ids`. Las
  métricas disponibles siguen en `metrics`; las recomendaciones se basan en metadatos.
- `collection.preparation.selection_method`: `views_desc` o `id_asc_no_known_views`.
  Si hay vistas conocidas, no se rellenan plazas con publicaciones sin vistas.
- Sin publicaciones utilizables se devuelve 422 `no_usable_videos`, sin IA.
- Una sola captura no demuestra crecimiento, tendencia ni causalidad.

## Filtros y capacidades del recolector

`platform` se envía como `redes: [platform]`. Tema, días, espera y estados se
mantienen. Las fechas exactas e idioma siguen siendo filtros locales; no se exige
coincidencia literal del tema en cada título.

El código revisado del recolector aplica país como región de búsqueda solo en
YouTube; no filtra por país LinkedIn ni TikTok. Se devuelve una limitación explícita.
En los ejemplos se omiten país e idioma para no descartar datos desconocidos.

El soporte del backend no garantiza resultados externos: el recolector necesita
sus propios accesos/proveedores y, en TikTok, cuentas semilla configuradas por su
responsable. No se configura nada de esto en el backend principal.

## Contrato de IA y compatibilidad

Se conserva el nombre público `videos` de `/analyze` y la clase `Video`; ahora
representan publicaciones. Se añade `platform`, inferible de `yt:`, `tt:` o `li:`.
Los IDs antiguos sin prefijo de YouTube siguen admitidos. Los prefijos explícitos
deben coincidir con plataforma y dominio HTTPS. Se admite `lnkd.in` para LinkedIn.

Se añade `shares`, por defecto `null`. LinkedIn/TikTok admiten `title: null` si
`description` tiene texto. YouTube sigue requiriendo título. No se descargan URLs.
`/analyze` rechaza mezclar plataformas en la misma solicitud.

## Actualizar Render en este orden

1. Publicar los cambios de ambas carpetas en la rama conectada. No se hicieron
   commits ni push automáticamente.
2. Desplegar primero **el servicio IA**, con el esquema ampliado.
3. Desplegar después **el backend principal**. Instala también `ai_service` como
   dependencia de esquemas; el análisis sigue siendo HTTP a `AI_ANALYZE_URL`.
4. No hay nuevas variables. Mantener las URLs que ya funcionan.

Si se actualiza principal pero no IA, el servicio antiguo puede rechazar los
campos nuevos, URLs de otras redes o títulos nulos. No confundirlo con falta de datos.

## Postman

- POST `https://tred-radar.onrender.com/research`.
- No Auth; `Content-Type: application/json`.
- Body raw JSON: `research_linkedin.json` o `research_tiktok.json` de esta carpeta.
- Empieza con `sample_size: 1`, una petición por vez. No se ejecutaron búsquedas
  reales de estas redes durante el desarrollo de este cambio.
- Comprueba `metrics`, plataforma de `sources`, referencias, limitaciones y
  `collection.simulated: false`. Ranking vacío con vistas desconocidas es correcto.
- Un fallo de recolección no se reemplaza con datos ficticios.

Los tests locales ejercitan las tres plataformas con fixtures y aplicación real
de IA con inferencia simulada. No consumen cuotas externas.
