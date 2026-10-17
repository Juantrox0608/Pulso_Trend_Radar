# Contrato de datos: Métrica (v1.0)

La fuente de verdad es [`src/radar/contrato/metrica.py`](../src/radar/contrato/metrica.py).
Una `Metrica` representa los contadores observados para una publicación en una captura.
No contiene autor, usuario ni enlace original. Hereda `schema_version = "1.0"`,
es inmutable y rechaza campos extra.

## Campos

| Campo | Tipo | Obligatorio | Regla |
|---|---|---|---|
| `publicacion_id` | texto | Sí | Patrón de `Publicacion.id`: `yt:`, `tt:` o `li:` + identificador |
| `capturada_en` | fecha y hora con zona | Sí | UTC; idéntica a la de su publicación en esa captura |
| `vistas` | entero ≥ 0 o vacío | No | `None`/JSON `null` si no se ve |
| `likes` | entero ≥ 0 o vacío | No | Reacciones en LinkedIn |
| `comentarios` | entero ≥ 0 o vacío | No | No se sustituye lo oculto por cero |
| `compartidos` | entero ≥ 0 o vacío | No | Siempre vacío en YouTube |
| `origen` | texto | Sí | `api_oficial` o `csv_manual` |

**Vacío no es cero:** cero es una observación válida. El contrato exige al menos
un contador con valor. Si todos faltan, el recolector conserva la publicación
y no crea una métrica. Rechaza negativos, fracciones y booleanos.

## Entrega

`youtube.buscar_con_metricas(...)` y `csv_manual.leer_con_metricas(ruta)` devuelven
la tupla `(publicaciones, metricas)`. Las funciones anteriores devuelven solo
publicaciones, delegando en las nuevas. Ahora las dos CLI imprimen:

```json
{"publicaciones": [], "metricas": []}
```

Es un cambio del formato de la CLI: los consumidores deben leer las dos claves.
YouTube solicita `statistics` en el mismo `videos.list`; no agrega llamadas.
Los contadores ausentes se conservan como `null`.
[Referencia de estadísticas de YouTube](https://developers.google.com/youtube/v3/docs/videos#statistics).

## Capturas del CSV

`fecha_captura` es opcional y acepta `AAAA-MM-DD`, `DD/MM/AAAA` o fecha y hora
ISO con zona. Una fecha sin hora significa 00:00 UTC. Si está vacía se usa la
fecha de modificación del CSV, para la publicación y su métrica.
Reimportar el mismo archivo sin modificarlo produce exactamente las mismas capturas.

`vistas`, `reacciones` (a `likes`), `comentarios` y `compartidos` son opcionales.
Se aceptan `1200`, `1.200`, `1,2 mil`, `12K`, `12 mil`, `1,5M` y `1.5 M`.
Punto sin sufijo significa grupos de tres cifras; sin sufijo no se admiten
decimales. `12.5`, `1,200` y un resultado fraccionario como `1,2345 mil` son
errores de fila. No se redondea ni se convierten celdas vacías en ceros.

Editar o copiar un archivo puede cambiar su fecha de modificación sin actualizar
las métricas: usa `fecha_captura` para registrar cuándo las observaste realmente.
Guardar el mismo dato otra vez no demuestra crecimiento ni aceleración.

## Tabla sugerida (Postgres / DuckDB)

```sql
CREATE TABLE metrica (
  publicacion_id  TEXT        NOT NULL REFERENCES publicacion (id),
  capturada_en    TIMESTAMPTZ NOT NULL,
  vistas          BIGINT      CHECK (vistas >= 0),
  likes           BIGINT      CHECK (likes >= 0),
  comentarios     BIGINT      CHECK (comentarios >= 0),
  compartidos     BIGINT      CHECK (compartidos >= 0),
  origen          TEXT        NOT NULL CHECK (origen IN ('api_oficial','csv_manual')),
  PRIMARY KEY (publicacion_id, capturada_en),
  CHECK (vistas IS NOT NULL OR likes IS NOT NULL OR comentarios IS NOT NULL OR compartidos IS NOT NULL)
);
```

La inserción selecciona las columnas de esta tabla; `schema_version` viene en
el JSON como en el contrato de publicación, pero no es columna del SQL sugerido.
Inserta primero la publicación. **Cada captura nueva es una fila nueva**: no
sobrescribas las anteriores. Repetir `(publicacion_id, capturada_en)` viola la
clave primaria; el consumidor puede ignorar el duplicado. La recolección no
implementa persistencia, deduplicación ni borrado de datos.

Las estadísticas públicas de YouTube obtenidas sin autorización del propietario
no se conservan más de 30 días. El consumidor debe borrar las capturas vencidas;
volver a pedir el valor actual no renueva la antigüedad de una captura histórica.
[Política oficial, sección III.E.4.b](https://developers.google.com/youtube/terms/developer-policies#e.-handling-youtube-data-and-content).
La comprobación del SQL en DuckDB y la corrida real de YouTube quedan para la
revisión de Claude; no se probaron aquí.
