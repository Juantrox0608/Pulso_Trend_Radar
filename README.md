# Radar de tendencias

Buscador de tendencias de bajo costo: encuentra los temas que **apenas empiezan a crecer** en YouTube, TikTok y
LinkedIn, explica por qué está funcionando cada uno y filtra lo que le sirve a una audiencia concreta.

## Qué pregunta responde

> ¿Qué temas están creciendo esta semana sobre lo que me interesa, por qué y cómo los aprovecho?

El tema lo elige quien busca: una industria, una tecnología, una marca o un formato. Por ejemplo: "inteligencia
artificial en México", "finanzas personales en TikTok" o "videos cortos de educación".

## Primera versión: inteligencia artificial

Arrancamos con un solo tema para validar el radar: **tendencias de IA para ejecutivos y equipos de Latinoamérica
que están aprendiendo IA**. La pregunta de esta versión es:

> ¿Cuáles son los 10 temas de IA que más están creciendo esta semana, por qué y cómo los adaptamos?

Una vez probado con IA, el mismo radar se abre a cualquier otro tema.

## Qué hace

1. **Busca.** Escribes un tema o una palabra clave y el radar revisa lo que se está publicando en las tres
   plataformas.
2. **Detecta temprano.** Compara el crecimiento de cada subtema con su propia historia reciente y marca los que
   aceleran mientras todavía tienen poco volumen.
3. **Explica por qué funcionó.** Para las piezas que más crecen analiza el gancho, el formato, el tema, el momento y
   el tipo de autor.
4. **Filtra por audiencia.** Prioriza por país, industria y tipo de público.

## Cómo funciona

```
Buscar  →  Recolectar  →  Agrupar en temas  →  Medir crecimiento  →  Explicar  →  Ranking
```

- **Buscar:** el usuario define el tema, el país y la audiencia.
- **Recolectar:** datos públicos de YouTube, TikTok y LinkedIn.
- **Agrupar en temas:** cada pieza se asigna a un subtema.
- **Medir crecimiento:** velocidad, aceleración y cantidad de autores distintos por subtema.
- **Explicar:** un modelo de IA resume por qué crece cada subtema y cómo aprovecharlo.
- **Ranking:** el resultado se muestra en un dashboard y en un informe corto.

## Principios

- Solo contenido público.
- Nada de datos personales.
- Bajo costo: herramientas gratuitas o casi gratuitas.

## Estado

En desarrollo.

## Recolección YouTube (paso 1)

Desde PowerShell en la raíz del repositorio:

```powershell
python -m venv .venv
./.venv/Scripts/python -m pip install -e ".[dev]"
./.venv/Scripts/python -m pytest -q
./.venv/Scripts/python -m radar.recoleccion.youtube "agentes de IA" --pais MX --dias 7
```

Juan configura `YOUTUBE_API_KEY` y `AUTOR_HASH_SAL` en el entorno del proceso,
fuera del repositorio. El recolector no carga `.env`: si las claves están en
`%USERPROFILE%\secretos_hackaton\.env`, cárgalas en la sesión de PowerShell antes de correrlo:

```powershell
Get-Content "$env:USERPROFILE\secretos_hackaton\.env" | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:$k" $v }
```

No pegues credenciales en comandos que queden guardados en el historial. Mantén la misma sal entre capturas
para que el seudónimo del autor sea estable.

Devuelve un array JSON de `radar.contrato.Publicacion`. Para usarlo desde Python:

```python
from datetime import datetime, timedelta, timezone
from radar.recoleccion.youtube import buscar_publicaciones

publicaciones = buscar_publicaciones(
    "agentes de IA", "MX", "es", datetime.now(timezone.utc) - timedelta(days=7)
)
```

Las pruebas usan fixtures sintéticos y variables ficticias, con la red bloqueada.
Hace una llamada a [search.list](https://developers.google.com/youtube/v3/docs/search/list)
y, si hay IDs, una a [videos.list](https://developers.google.com/youtube/v3/docs/videos/list).
Consulta solo la primera página, hasta 50 videos; no promete un mínimo de resultados.
Omite videos eliminados o no devueltos en el lote de detalles.
El país es la región de búsqueda, no el país del autor. El idioma proviene del
video; puede faltar o diferir del idioma buscado. El umbral de 180 segundos
aproxima el formato corto, sin certificar que sea un Short.
Usa `channelId` en memoria solo para calcular el hash, y `channelTitle` solo para quitar
de las etiquetas el nombre del canal; ninguno de los dos se devuelve ni se guarda.
No guarda respuestas crudas ni agrega dependencias.

Pendiente: revisión de Claude y comprobación de Juan con credenciales reales
(al menos 10 publicaciones con enlace, texto y fecha). Esta comprobación real
no se ha realizado y no forma parte de las pruebas sin red.

## Recolección CSV manual (paso 2)

Desde PowerShell en la raíz del repositorio, con el entorno del paso 1 instalado
y `AUTOR_HASH_SAL` configurada en el proceso, ejecuta:

```powershell
./.venv/Scripts/python -m pytest -q
./.venv/Scripts/python -m radar.recoleccion.csv_manual tests/fixtures/manual_excel.csv
./.venv/Scripts/python -m radar.recoleccion.csv_manual data/raw/publicaciones_manual.csv
```

El primer CSV contiene dos publicaciones ficticias para comprobar la instalación.
El segundo es el archivo real de Juan, ignorado por Git. El importador no lee `.env`
ni necesita la clave de YouTube. Usa la misma sal entre capturas para mantener
estable el hash del autor. Para verificar sin secretos se puede usar una sal
ficticia en un proceso de prueba; sus hashes no deben mezclarse con los reales.

El encabezado debe incluir `url`, `fecha_publicacion`, `texto` y `formato`, en
cualquier orden. Opcionales: `autor`, `hashtags`, `tipo_autor`, `idioma`, `pais`.
Se ignoran las columnas de métricas: vistas, reacciones, comentarios y compartidos.
Hashtags y métricas pueden quedar vacíos: un dato ausente no equivale a cero.

Acepta UTF-8 con o sin BOM y Windows-1252, separados por coma o punto y coma.
Los textos con comas, separadores o saltos de línea deben ir entre comillas CSV
(Excel se encarga al guardar). Las fechas admiten `AAAA-MM-DD`, `DD/MM/AAAA`
o fecha y hora ISO con zona horaria; una fecha sin hora se toma como 00:00 UTC.

Formatos: `video_corto`, `video_largo`, `post_texto`, `post_imagen`, `carrusel`,
`articulo`. También acepta `video 53s`: guarda la duración y usa el umbral de
180 segundos para clasificar el video. En tipo de autor acepta empresa, medio,
experto, creador, institución (`institucion`) o desconocido; vacío equivale a
desconocido y se ignora una aclaración posterior como `(educación)`.

Idiomas: códigos (`es`, `es-419`) o español, inglés y portugués. Países: código
de dos letras o México, Colombia, Argentina, Perú, Chile, Brasil, España y
Estados Unidos. `N/D` en país se guarda como ausente.

El autor se toma de la columna `autor`; si está vacía, del usuario en `/@usuario/video/`
de TikTok o del tramo previo al primer `_` en `/posts/` de LinkedIn. Si no puede
extraerse, la fila falla. Los hashtags iguales al autor o al usuario del enlace (`#AnaPerez`) se quitan.
Solo sale su hash y la URL canónica del contrato;
no se devuelve la columna de autor ni se guardan respuestas crudas.

Los enlaces se procesan localmente, sin red. El contrato admite enlaces cortos
`lnkd.in/X/CODIGO` y devuelve su forma canónica, sin usuario ni parámetros.
Se conserva la limitación del contrato: distintos enlaces cortos al mismo post
pueden producir identificadores distintos. Completa `autor` si el enlace no lo contiene.
El identificador de actividad también puede obtenerse de `highlightedUpdateUrn`
cuando la URL completa de LinkedIn incluye ese parámetro.
Una celda con dos enlaces pegados es inválida: debe contener solo una URL.

Si hay filas inválidas, el comando termina con código 1, lista sus líneas y
motivos por stderr y no imprime publicaciones parciales. Los valores originales
de los campos no aparecen en los errores. Los números corresponden al inicio
de cada registro en el archivo; un texto con saltos de línea puede ocupar varias.
