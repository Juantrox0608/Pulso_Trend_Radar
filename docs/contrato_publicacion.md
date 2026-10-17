# Contrato de datos: Publicación (v1.0)

Qué entrega la recolección y cómo guardarlo. La fuente de verdad es
[`src/radar/contrato/publicacion.py`](../src/radar/contrato/publicacion.py): si este documento no coincide con el
código, manda el código.

## Qué llega

La recolección devuelve una lista de `Publicacion` en JSON, ya validada:

- **YouTube** por la API oficial (`origen = api_oficial`).
- **TikTok y LinkedIn** desde un CSV cargado a mano (`origen = csv_manual`).
- **Sin datos personales:** el autor llega solo como `autor_hash`. Nunca nombre, usuario ni url original, y los
  hashtags iguales al autor se quitan.

## Campos

| Campo | Tipo | Obligatorio | Regla |
|---|---|---|---|
| `id` | texto | Sí, clave primaria | `yt:`, `tt:` o `li:` + id de la plataforma (`yt:dQw4w9WgXcQ`, `li:lnkd-e-abcd1234`) |
| `schema_version` | texto | Sí | Hoy siempre `"1.0"` |
| `plataforma` | texto | Sí | `youtube`, `tiktok`, `linkedin` |
| `url` | texto | Sí | Canónica, sin autor; se calcula desde `id` |
| `titulo` | texto ≤ 300 | No | Al menos uno de `titulo` o `texto` viene lleno |
| `texto` | texto ≤ 5.000 | No | Descripción o gancho |
| `hashtags` | lista de texto | Sí (puede ir vacía) | Sin `#`, minúsculas, sin repetidos |
| `formato` | texto | Sí | `video_corto`, `video_largo`, `post_texto`, `post_imagen`, `carrusel`, `articulo` |
| `duracion_segundos` | entero ≥ 0 | No | Solo videos |
| `idioma` | 2 letras | No | ISO 639-1 en minúsculas |
| `pais` | 2 letras | No | ISO 3166 en mayúsculas; en YouTube es el país de la búsqueda, no del autor |
| `tipo_autor` | texto | Sí | `empresa`, `medio`, `experto`, `creador`, `institucion`, `desconocido` |
| `autor_hash` | 16 caracteres | Sí | Hexadecimal; sirve para contar autores distintos |
| `publicada_en` | fecha y hora | Sí | UTC |
| `capturada_en` | fecha y hora | Sí | UTC; nunca anterior a `publicada_en` |
| `origen` | texto | Sí | `api_oficial`, `csv_manual`, `pagina_publica` |

## Tabla sugerida

```sql
CREATE TABLE publicacion (
  id                 TEXT PRIMARY KEY,
  schema_version     TEXT        NOT NULL DEFAULT '1.0',
  plataforma         TEXT        NOT NULL CHECK (plataforma IN ('youtube','tiktok','linkedin')),
  url                TEXT        NOT NULL,
  titulo             VARCHAR(300),
  texto              VARCHAR(5000),
  hashtags           TEXT[]      NOT NULL DEFAULT '{}',
  formato            TEXT        NOT NULL CHECK (formato IN ('video_corto','video_largo','post_texto','post_imagen','carrusel','articulo')),
  duracion_segundos  INTEGER     CHECK (duracion_segundos >= 0),
  idioma             CHAR(2),
  pais               CHAR(2),
  tipo_autor         TEXT        NOT NULL DEFAULT 'desconocido' CHECK (tipo_autor IN ('empresa','medio','experto','creador','institucion','desconocido')),
  autor_hash         CHAR(16)    NOT NULL,
  publicada_en       TIMESTAMPTZ NOT NULL,
  capturada_en       TIMESTAMPTZ NOT NULL,
  origen             TEXT        NOT NULL CHECK (origen IN ('api_oficial','csv_manual','pagina_publica')),
  CHECK (titulo IS NOT NULL OR texto IS NOT NULL),
  CHECK (capturada_en >= publicada_en)
);

CREATE INDEX idx_publicacion_plataforma_fecha ON publicacion (plataforma, publicada_en);
CREATE INDEX idx_publicacion_autor ON publicacion (autor_hash);
```

En DuckDB cambia una línea: `hashtags VARCHAR[] NOT NULL DEFAULT []`. Probado en DuckDB con 26 publicaciones reales;
en Postgres no se probó.

## Reglas para guardar

- Una fila por `id`: si la publicación vuelve a llegar, se actualiza (`capturada_en`, `titulo`, `texto`,
  `hashtags`); `publicada_en` y `autor_hash` no cambian.
- Fechas siempre con zona horaria, en UTC.
- No agregar columnas con datos del autor. Un campo nuevo se agrega primero al contrato.
- Guardar `schema_version` para saber con qué versión entró cada fila.

## Ejemplo

```json
{
  "schema_version": "1.0",
  "id": "tt:7412345678901234567",
  "plataforma": "tiktok",
  "url": "https://www.tiktok.com/@/video/7412345678901234567",
  "titulo": null,
  "texto": "3 prompts que uso todos los días en la oficina",
  "hashtags": ["ia", "productividad"],
  "formato": "video_corto",
  "duracion_segundos": 42,
  "idioma": "es",
  "pais": "CO",
  "tipo_autor": "creador",
  "autor_hash": "decc2f9ef1329ad9",
  "publicada_en": "2026-10-15T14:00:00Z",
  "capturada_en": "2026-10-17T03:00:00Z",
  "origen": "csv_manual"
}
```

## Pendiente

Tablas que todavía no tienen contrato: `metrica` (vistas, likes, comentarios y compartidos por captura; YouTube solo
permite guardar sus estadísticas 30 días), `tema`, `tendencia`, `analisis_ia` y `senal_plataforma`.

Las capturas automatizadas de páginas públicas usan `pagina_publica`; no son una API oficial.
