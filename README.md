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

1. **Busca.** Escribes un tema o una palabra clave y el radar revisa lo que se está publicando en las tres plataformas.
2. **Detecta temprano.** Compara el crecimiento de cada subtema con su propia historia reciente y marca los que aceleran mientras todavía tienen poco volumen.
3. **Explica por qué funcionó.** Para las piezas que más crecen analiza el gancho, el formato, el tema, el momento y el tipo de autor.
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

---

## Base y API (FastAPI + Neon PostgreSQL)

Módulo central de persistencia y servicios REST del Radar. Conecta los datos validados de recolección, el análisis editorial generado por IA y expone la API requerida por el frontend en Next.js.

### 1. Instalación y dependencias

Desde PowerShell en la raíz del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

### 2. Configuración de Base de Datos (`.env`)

Crea un archivo `.env` en la raíz (puedes basarte en `.env.example`):

```env
# Cadena de conexión de Neon PostgreSQL (usar conexión con pooler)
DATABASE_URL=postgresql://usuario:password@ep-xyz-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require
```

> **Nota de resiliencia:** Si `DATABASE_URL` no está definida, el backend activa automáticamente un fallback local a SQLite (`sqlite:///./radar.db`), asegurando que el equipo pueda trabajar sin conexión a internet.

### 3. Ejecución del servidor

Para iniciar el servidor con recarga automática:

```powershell
.\.venv\Scripts\uvicorn radar.api:app --host 0.0.0.0 --port 8000 --reload
```

Una vez levantado:
- **Swagger UI interactivo:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **OpenAPI JSON:** [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)
- **Health Check:** [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

### 4. Endpoints principales

| Método | Endpoint | Descripción |
| :--- | :--- | :--- |
| `GET` | `/api/trends` | Búsqueda y listado de tendencias ordenadas por velocidad de crecimiento con análisis editorial. Admite `?query=`, `?platform=` y `?category=`. |
| `GET` | `/api/trends/{id}` | Detalle de una tendencia individual con métricas y ganchos. |
| `GET` | `/api/opportunities` | Listado de oportunidades editoriales guardadas o propuestas. |
| `PATCH` | `/api/opportunities/{id}` | Actualización de estado editorial (`Pendiente`, `Aprobada`, `Descartada`). |
| `POST` | `/api/publicaciones` | Ingesta de publicaciones validadas desde el módulo de recolección (YouTube, TikTok, LinkedIn). |
| `POST` | `/api/trends/{id}/analizar` | Disparo del enriquecimiento editorial por IA. |

### 5. Pruebas automáticas

Para ejecutar la suite completa de pruebas (contratos de datos, normalización de URLs y endpoints de API):

```powershell
.\.venv\Scripts\python -m pytest -v
```
