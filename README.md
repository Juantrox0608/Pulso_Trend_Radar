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
No solicita `channelTitle`: usa `channelId` en memoria solo para calcular el hash.
No guarda respuestas crudas ni agrega dependencias.

Pendiente: revisión de Claude y comprobación de Juan con credenciales reales
(al menos 10 publicaciones con enlace, texto y fecha). Esta comprobación real
no se ha realizado y no forma parte de las pruebas sin red.
