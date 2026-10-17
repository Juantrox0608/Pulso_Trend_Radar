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

## Contrato de datos

Formato único de cada publicación, campos, tabla sugerida y reglas para guardar:
[docs/contrato_publicacion.md](docs/contrato_publicacion.md).

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

La CLI devuelve `{"publicaciones": [...], "metricas": [...]}`. Las estadísticas
se piden en el mismo lote de detalles, sin llamadas adicionales. Para usarlo desde Python:

```python
from datetime import datetime, timedelta, timezone
from radar.recoleccion.youtube import buscar_con_metricas

publicaciones, metricas = buscar_con_metricas(
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

El paso 1 ya se comprobó con YouTube real. La nueva salida con métricas del paso 4
se comprueba con respuestas ficticias y se corrió con YouTube real (1.010 videos, 2026-10-17).

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
cualquier orden. Opcionales: `autor`, `hashtags`, `tipo_autor`, `idioma`, `pais`,
`fecha_captura`, `vistas`, `reacciones`, `comentarios`, `compartidos`.
La CLI devuelve `{"publicaciones": [...], "metricas": [...]}`; `reacciones` pasa a `likes`.
Hashtags y métricas pueden quedar vacíos: un dato ausente no equivale a cero.
Si faltan las cuatro métricas, la publicación sale sin una fila en `metricas`.
Se aceptan cantidades como `1200`, `1.200`, `1,2 mil`, `12K`, `12 mil`, `1,5M`
y `1.5 M`; se rechazan negativos, cantidades ambiguas (`12.5`) y resultados
fraccionarios (`1,2345 mil`), sin redondear.

`fecha_captura` acepta los mismos formatos que `fecha_publicacion` y es **obligatoria
en las filas con métricas**: es el día en que viste esos números. Editar el CSV cambia
su fecha de modificación, así que no sirve para fechar métricas. En filas sin métricas
puede quedar vacía y se usa la fecha de modificación del archivo para la publicación.

Desde Python, `leer_con_metricas(ruta)` devuelve `(publicaciones, metricas)`.
`buscar_publicaciones(...)` y `leer_publicaciones(ruta)` conservan la salida de
solo publicaciones y delegan en las funciones nuevas.
Consulta [el contrato de métricas y la tabla SQL](docs/contrato_metrica.md).

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

## TikTok desde URL (paso 5)

Instala las dependencias del proyecto, incluido `yt-dlp`, mediante el procedimiento de instalación anterior.
Añade `--completar-tiktok` al importador para consultar metadatos públicos: basta `url` en esas filas;
`texto` y `fecha_publicacion` del CSV tienen prioridad. `tipo_autor`, `idioma` y `pais` son opcionales.
Las métricas son las obtenidas en la consulta y usan `pagina_publica`, con fecha de captura actual UTC.
Sin la opción no se consulta internet. La salida sigue teniendo `publicaciones` y `metricas`.

Es una vía no oficial, contraria a los términos de TikTok, sin sesión ni descarga del video.
Se solicita la metadata de cada video (yt-dlp puede hacer varias peticiones HTTP internamente),
con 1,5 segundos entre videos y máximo 100 por corrida. Los fallos se listan por línea y no se devuelve una importación parcial.
El formato se aproxima por duración: hasta 180 segundos es `video_corto`.

Comprobación local sin activar la consulta, con una sal ficticia y un CSV ficticio:

```powershell
$env:AUTOR_HASH_SAL = 'sal_ficticia_solo_prueba'
./.venv/Scripts/python -m radar.recoleccion.csv_manual tests/fixtures/manual_excel.csv
```

Corrida real (2026-10-17): 13 de 13 TikToks completos, con duración y métricas.

## LinkedIn desde URL (paso 6)

Añade `--completar-linkedin` al importador del CSV para leer la página pública sin sesión.
En esas filas basta `url` (también acepta `lnkd.in`); el destino debe ser una publicación de
`linkedin.com/posts/` o `linkedin.com/feed/update/`. Las opciones de TikTok y LinkedIn se pueden combinar.
El texto y la fecha no vacíos del CSV tienen prioridad; se completan los ausentes.
Se aceptan `SocialMediaPosting` y `VideoObject` del JSON-LD (posts de texto y video).
Las reacciones, comentarios y compartidos vienen de `interactionStatistic`; si falta
`CommentAction`, se usa `commentCount`. El autor se obtiene de `author` o `creator`.
El texto se toma de `articleBody`, `text` o `description`, nunca de `headline`;
no se inventan vistas ni conteos ocultos. Todas estas capturas usan `pagina_publica`,
con fecha actual UTC y sin exigir `fecha_captura` ni usar los números antiguos del CSV.

Esta vía no oficial es contraria al Acuerdo de Usuario de LinkedIn; Juan autorizó únicamente
el volumen pequeño del prototipo. Hay una pausa de 3 segundos entre posts y máximo 100
por corrida (el límite de TikTok se cuenta por separado). No usa cookies, login ni reintentos.
Solo un HTTP 429/999 o una redirección a `/login`, `/uas`, `/authwall` o `/checkpoint`
detiene toda la corrida, incluidas las filas posteriores de TikTok, y lista las líneas pendientes.
Un formulario de login en el menú no cuenta como bloqueo. Una página sin JSON-LD de post
válido produce un error de fila y se siguen consultando las demás; al terminar se listan
los errores sin devolver una importación parcial. Los cambios del sitio pueden romper la extracción.

El `formato` no vacío del CSV tiene prioridad (también acepta `video Ns`). Sin formato manual,
un `SocialMediaPosting` usa `post_texto`; un `VideoObject` usa la duración ISO 8601 para
elegir `video_corto` hasta 180 segundos o `video_largo` por encima. Si falta la duración
o no se entiende, queda vacía y se usa `video_corto`.

Los comandos de CSV y YouTube escriben el JSON en UTF-8, incluidos acentos y emoji,
también cuando stdout se redirige directamente a un archivo.

Las menciones se sustituyen por `@[usuario]` y se eliminan del texto los nombres y usuarios
conocidos del autor; eso no equivale a detectar todos los nombres que un post pueda mencionar.
No se guardan HTML, cookies ni respuestas crudas. También se reparan los acentos del texto manual.

Comprobación local sin activar las consultas, con datos y sal ficticios:

```powershell
$env:AUTOR_HASH_SAL = 'sal_ficticia_solo_prueba'
./.venv/Scripts/python -m radar.recoleccion.csv_manual tests/fixtures/manual_excel.csv
./.venv/Scripts/python -m radar.recoleccion.csv_manual --help
```

Corrida real (2026-10-17): 13 de 13 posts completos (texto, fecha, reacciones y comentarios; LinkedIn no
publica compartidos). Los `CHECK` de `pagina_publica` de ambos contratos se comprobaron en DuckDB.

## LinkedIn: descubrir por tema (paso 7)

El módulo `radar.recoleccion.linkedin_buscar` busca URLs por tema mediante OpenRouter con
el plugin web de Exa, un buscador de terceros, y completa los posts con el recolector público
de LinkedIn. Solo usa las citas de la respuesta de búsqueda: no guarda ni imprime los textos,
nombres o resúmenes que devuelva Exa. La lectura de LinkedIn sigue siendo no oficial, sin
sesión ni cookies, con las limitaciones del paso 6.

Necesita `OPENROUTER_API_KEY` y `AUTOR_HASH_SAL` ya definidas en el entorno; el programa
no carga archivos `.env`. Usa el modelo `deepseek/deepseek-v4-flash-0731` sin razonamiento.
En la prueba del 17/10/2026 se midieron aproximadamente **USD 0,007 por consulta de 10 resultados**;
es una referencia, no una tarifa garantizada. El resumen muestra el costo que reporta `usage.cost`.
Cada consulta hace una llamada a OpenRouter; no hay reintentos automáticos.

`--consulta` se puede repetir hasta 20 veces; `--resultados` admite 1–10 resultados por consulta.
Se descartan perfiles, empresas y artículos, y se reúnen posts únicos por ID entre consultas.
`--max` limita los intentos de lectura a 1–100, incluso si algunos posts fallan, con pausa de
3 segundos entre intentos. Tras resolver redirecciones también se deduplica la salida.
Con `--dias N`, cada búsqueda incorpora el periodo y el mes actual en español, calculados en UTC:
por ejemplo, «publicaciones de los últimos 7 días (octubre de 2026) en LinkedIn: agentes de IA».
Antes de abrir LinkedIn se descartan los posts antiguos usando la fecha del ID de actividad
(`(int(id) >> 22) / 1000`, segundos Unix). Esas URLs cuentan en `fuera_fecha`, sin consumir
intentos de `--max` ni pausas. Después se comprueba también `publicada_en`, incluso si el ID
no es numérico o no permite calcular una fecha. Sin `--dias`, la consulta y las fechas se conservan.
No se garantiza que el buscador encuentre posts recientes ni que reúna la cantidad solicitada.

Mediciones del 17/10/2026: 8 consultas dieron 78 URLs, 78 posts completados, 0 omitidos,
USD 0,060 y 5 min 35 s; solo 5 posts eran de los últimos 7 días y 27 de los últimos 30
(mediana: 57 días). La fecha del ID coincidió con `datePublished` en 78/78, con menos de 1 s
de diferencia. En una comparación de la misma consulta, añadir el periodo mejoró la mediana
de 113 a 9 días y los posts del último mes de 2/10 a 9/10; 4/10 eran de la última semana.
Pedir 25 resultados diluyó la muestra (mediana: 60 días) y costó el triple; se mantiene el tope de 10.
Son mediciones históricas del prototipo, no garantías de cobertura o costo.

Una búsqueda fallida se cuenta en `consultas_fallidas` y se continúa con las demás, sin reintentar.
Si fallan todas, el comando termina con error y sin JSON. Una respuesta válida sin resultados
cuenta como búsqueda correcta. El costo suma solo lo reportado por respuestas válidas;
no permite conocer un posible cargo de consultas fallidas.

Un post caído o sin JSON-LD se omite y se cuenta. Un HTTP 429/999 o una redirección de acceso
detiene las lecturas de LinkedIn, sin reintentar, y devuelve lo reunido con un aviso en stderr.
Las búsquedas de OpenRouter se reúnen antes de empezar las lecturas de LinkedIn.
La salida JSON de siempre (`publicaciones`, `metricas`) va a stdout en UTF-8, con `pagina_publica`.
Por stderr se informa: consultas intentadas, consultas fallidas (`consultas_fallidas`), URLs únicas
encontradas antes del filtro, posts completados, omitidos, fuera de fecha y costo total USD.
Completados cuenta lecturas válidas antes de filtrar por `publicada_en`
y deduplicar redirecciones; puede superar el número de publicaciones devueltas.

Comprobación sin red ni credenciales:

```powershell
./.venv/Scripts/python -m radar.recoleccion.linkedin_buscar --help
```

Ejemplo de sintaxis con dos consultas y comprobación del error por falta de clave, sin gasto:

```powershell
Remove-Item Env:OPENROUTER_API_KEY -ErrorAction SilentlyContinue
$env:AUTOR_HASH_SAL = 'sal_ficticia_solo_prueba'
./.venv/Scripts/python -m radar.recoleccion.linkedin_buscar --consulta "agentes de IA en español LatAm" --consulta "automatización con IA para empresas LatAm" --dias 7 --max 100 --resultados 10
```

El último comando debe salir con código 1, sin JSON y con `Falta OPENROUTER_API_KEY en el entorno`.
Con el entorno real configurado, la misma sintaxis ejecuta búsquedas de pago y lecturas públicas;
la comprobación real de cobertura y costo del paso 7b queda pendiente de revisión.

## TikTok en segundo plano (paso 8)

Descubre cuentas semilla y lista sus videos públicos con yt-dlp, sin sesión, cookies ni descarga.
Es una vía **no oficial**. La cobertura depende de las cuentas semilla: no es un censo de TikTok.
Solo usa yt-dlp y OpenRouter; no añade dependencias. `AUTOR_HASH_SAL` debe estar cargada en el entorno
para capturar. Los comandos no cargan archivos de secretos.

Mediciones del 17/10/2026: listar `tiktokuser:<channel_id>` devolvió 30 videos en 2,3 s,
todos de los últimos 7 días, con descripción, fecha, duración y métricas en la misma lista;
no hace falta consultar cada video. Consultar el perfil por `@usuario` falló.
Exa encontró videos del tema con mediana de 114 días: se usa para descubrir cuentas,
y después se listan sus videos nuevos. Son mediciones del prototipo, no garantías.

Crear semillas desde las URLs del CSV (acepta Excel con `;`, BOM o CP1252):

```powershell
./.venv/Scripts/python -m radar.recoleccion.tiktok_cuentas semillas --desde-csv data\raw\publicaciones_manual.csv
```

Descubrir cuentas por tema con Exa, buscador de terceros a través de OpenRouter (requiere
`OPENROUTER_API_KEY` y saldo para la búsqueda; esta parte no es gratis):

```powershell
./.venv/Scripts/python -m radar.recoleccion.tiktok_cuentas semillas --consulta "agentes de IA en empresas"
```

`--consulta` se puede repetir hasta 20 veces. Ambas vías añaden como máximo 50 cuentas nuevas
por corrida, sin duplicados; esperan 1,5 s entre videos consultados para obtener la cuenta.
Una URL fallida se cuenta y se continúa. Las semillas se guardan en `data/raw/tiktok_cuentas.txt`,
un identificador por línea, sin nombres ni usuarios; `data/raw/` está fuera de Git.
`--semillas RUTA` permite elegir otro archivo tanto en `semillas` como en `capturar`.

Captura única; por defecto usa los últimos 7 días, 30 entradas por cuenta y hasta 300 videos únicos:

```powershell
./.venv/Scripts/python -m radar.recoleccion.tiktok_cuentas capturar --dias 7 --por-cuenta 30 --max 300 --salida-dir data\raw\tiktok
```

Una consulta plana por cuenta, con pausa de 3 s entre cuentas. Descarta videos antiguos por
la fecha del ID (`int(id) >> 32`, segundos Unix) antes de convertirlos; también comprueba la
fecha publicada. Omite entradas incompletas. Una cuenta fallida se cuenta y se sigue;
tres fallos consecutivos o un HTTP 403/429 detienen la captura sin reintentar y guardan lo reunido.
También se detiene la repetición periódica ante ese bloqueo. Ctrl+C conserva las cuentas ya leídas.

Cada corrida escribe un JSON UTF-8 `data/raw/tiktok/tiktok_AAAA-MM-DDTHHMM.json` con
`publicaciones` y `metricas`. Si ya existe un archivo del mismo minuto, añade segundos y microsegundos.
La escritura es temporal y luego se renombra; no publica JSON incompleto. No guarda respuestas crudas.
La salida contiene hash del autor, menciones `@[usuario]` y URL canónica sin usuario.
El resumen por stderr cuenta cuentas, cuentas fallidas, videos guardados, fuera de fecha, omitidos,
descartados por tema y lotes sin filtrar. Cada captura nueva conserva otra observación de métricas
para el mismo video, útil para comparar crecimiento, velocidad y aceleración.

Filtro opcional de relevancia, con `OPENROUTER_API_KEY` cargada:

```powershell
./.venv/Scripts/python -m radar.recoleccion.tiktok_cuentas capturar --tema "inteligencia artificial en la educación"
```

Usa `nvidia/nemotron-3-super-120b-a12b:free`, razonamiento desactivado, hasta 30 textos por pedido.
Al modelo solo llegan textos anonimizados: sin enlaces ni datos de autor. Conserva los `SI`/`SÍ`.
Una respuesta vacía, incompleta o mal formada se reintenta una vez; si vuelve a fallar,
conserva ese lote sin filtrar y lo cuenta. Un HTTP 429 detiene el filtro durante esa corrida,
conserva los lotes pendientes y avisa. La siguiente captura puede volver a intentarlo.
Sin `--tema` no se hacen llamadas a OpenRouter durante la captura.

La prueba histórica de este filtro dio 30/30 respuestas en 3,5 s, USD 0 y coincidencia en 30/30;
no garantiza la clasificación futura ni disponibilidad. El límite indicado del plan gratis es
20 pedidos/minuto y 50/día: el comando espacia pedidos al menos 3,1 s y persiste el contador diario
UTC en `data/raw/tiktok_filtro_cuota.json`, incluidos reintentos y reinicios. Al agotarlo conserva
sin filtrar. Ese contador solo conoce pedidos de este comando: otros usos de la clave también
consumen la cuota del proveedor. Ejecuta una sola instancia del recolector por clave.

Para repetir en primer plano hasta Ctrl+C (intervalo mínimo: una hora después de cada corrida):

```powershell
./.venv/Scripts/python -m radar.recoleccion.tiktok_cuentas capturar --cada-horas 3 --tema "inteligencia artificial en la educación"
```

Para lanzarlo oculto desde PowerShell, situado en el repo y con las variables ya cargadas
(el proceso hijo las hereda), sin crear tareas programadas:

```powershell
New-Item -ItemType Directory -Force data\raw\tiktok | Out-Null
$captura = Start-Process -FilePath (Resolve-Path .\.venv\Scripts\python.exe) -WorkingDirectory (Get-Location).Path -ArgumentList '-u -m radar.recoleccion.tiktok_cuentas capturar --cada-horas 3 --tema "inteligencia artificial en la educación"' -WindowStyle Hidden -PassThru -RedirectStandardOutput data\raw\tiktok\proceso.stdout.log -RedirectStandardError data\raw\tiktok\proceso.stderr.log
$captura.Id
```

Para detener ese proceso oculto desde la misma sesión:

```powershell
Stop-Process -Id $captura.Id
```

`Stop-Process` es una parada forzada: las capturas terminadas quedan guardadas, pero se puede perder
la captura en curso. En primer plano usa Ctrl+C para guardar lo reunido. El directorio de salida
se protege con `.captura.lock`; si tras una parada forzada queda ese archivo, comprueba que el
proceso terminó antes de borrarlo. No ejecutes dos capturas simultáneas en el mismo directorio.

Comprobaciones sin red; los dos últimos comandos deben terminar con código 1 y mensaje claro
por falta de clave y de semillas, respectivamente. No ejecutan búsquedas ni capturas reales:

```powershell
./.venv/Scripts/python -m radar.recoleccion.tiktok_cuentas --help
./.venv/Scripts/python -m radar.recoleccion.tiktok_cuentas semillas --help
./.venv/Scripts/python -m radar.recoleccion.tiktok_cuentas capturar --help
Remove-Item Env:OPENROUTER_API_KEY -ErrorAction SilentlyContinue
./.venv/Scripts/python -m radar.recoleccion.tiktok_cuentas semillas --consulta "agentes de IA en empresas"
./.venv/Scripts/python -m radar.recoleccion.tiktok_cuentas capturar --semillas tests\fixtures\tiktok_sin_semillas.txt
```

La corrida real con las semillas del CSV, el filtro y dos observaciones separadas queda para revisión.
YouTube también anonimiza ahora las menciones y el nombre del canal en título y descripción.

## Recaptura de métricas de YouTube (paso 9)

Consulta estadísticas de videos conocidos sin volver a buscarlos. Requiere `YOUTUBE_API_KEY`
en el entorno; no necesita la sal. Acepta uno o varios JSON: tanto listas de publicaciones como
objetos `{publicaciones, metricas}`. Ignora otras plataformas y elimina ids repetidos.

Ejemplo para ejecutar con la clave ya cargada (usa red):

```powershell
./.venv/Scripts/python -m radar.recoleccion.youtube_metricas data\raw\youtube_2026-10-17.json --salida data\raw\youtube_metricas.json
```

Hace `videos.list` con `part=statistics`, hasta 50 ids por llamada (1 unidad de cuota por llamada).
Escribe `{publicaciones: [], metricas: [...]}`; sin `--salida`, imprime JSON en stdout. Cada lote lleva
la hora UTC de su consulta. Contador ausente significa `null`; cero sigue siendo cero. Un video sin
ningún contador no crea una métrica. El resumen en stderr indica ids, llamadas, métricas y videos
faltantes (ya no devueltos por YouTube). Conserva cada captura en un archivo distinto si quieres
comparar observaciones; las métricas de YouTube deben borrarse a los 30 días.

## Búsqueda general por tema (paso 9)

YouTube busca en MX, CO, AR, CL y PE; LinkedIn descubre publicaciones por tema; TikTok captura las
cuentas semilla existentes y aplica el filtro gratis de Nemotron. Por defecto son las tres redes,
los últimos 7 días y un único JSON sin repetir publicaciones ni métricas por id. Una red o un país
que falla se cuenta en stderr y las demás consultas siguen; si todas fallan, termina con error.
El resumen incluye avisos de capturas parciales, bloqueo o lotes que se conservaron sin filtrar.

Necesita `AUTOR_HASH_SAL`, `YOUTUBE_API_KEY` para YouTube y `OPENROUTER_API_KEY` para LinkedIn y
el filtro de TikTok. TikTok requiere semillas en `data/raw/tiktok_cuentas.txt`; su cobertura depende
de esas cuentas. LinkedIn y TikTok usan las vías públicas no oficiales descritas arriba, sin sesión
ni cookies. Exa tiene costo; el filtro comparte el contador diario existente de Nemotron.

Ejemplos para ejecutar con variables y semillas ya preparadas (usan red):

```powershell
./.venv/Scripts/python -m radar.recoleccion.buscar --tema "inteligencia artificial en la educación" --salida data\raw\busqueda.json
./.venv/Scripts/python -m radar.recoleccion.buscar --tema "inteligencia artificial en la educación" --dias 7 --redes youtube,linkedin --paises MX,CO --salida data\raw\busqueda.json
```

TikTok y LinkedIn ahora entregan título desde `title` o `headline`; si falta, usan la primera línea
útil del texto, anonimizada, sin enlaces y hasta 120 caracteres en un límite de palabra. Si queda
vacío, el título es `null`. El CSV manual conserva su comportamiento.

Para enviar a la API, añade `--enviar` con su URL base. Este ejemplo hace POST al servidor local:

```powershell
./.venv/Scripts/python -m radar.recoleccion.buscar --tema "inteligencia artificial en la educación" --salida data\raw\busqueda.json --enviar http://localhost:8000
```

Antes del primer POST guarda el JSON UTF-8. Sin `--salida`, al enviar crea una copia en
`data/raw/busqueda_<fecha UTC>.json`. Envía a `/api/publicaciones` en lotes de hasta 200 publicaciones
con sus métricas, con timeout de 30 s y sin reintentos. Si un lote falla, intenta los restantes,
conserva el archivo y termina con código 1 indicando los números de lotes no confirmados (desde 1).
Un timeout puede ocurrir después de que el servidor guarde el lote: comprueba la API antes de repetirlo.
Sin `--enviar` no hace POST.

Comprobaciones sin red: las ayudas terminan con código 0; los comandos sin clave terminan con 1.
Retiran las claves solo del entorno del proceso actual, sin leer archivos de secretos:

```powershell
./.venv/Scripts/python -m radar.recoleccion.youtube_metricas --help
./.venv/Scripts/python -m radar.recoleccion.buscar --help
Remove-Item Env:YOUTUBE_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:AUTOR_HASH_SAL -ErrorAction SilentlyContinue
./.venv/Scripts/python -m radar.recoleccion.youtube_metricas data\raw\youtube_2026-10-17.json
./.venv/Scripts/python -m radar.recoleccion.buscar --tema "inteligencia artificial en la educación" --redes youtube
```

Las corridas reales en tres redes, la recaptura de los 1.010 videos y la integración con trends/IA
quedan para la revisión del equipo.
