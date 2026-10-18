"""Modelos de base de datos SQLModel para Radar de Tendencias."""

from datetime import datetime, timezone
from sqlmodel import Field, SQLModel

from radar.contrato.trend import Opportunity, Trend


class TrendDB(SQLModel, table=True):
    """Almacena tendencias con métricas consolidadas y análisis de IA."""

    __tablename__ = "trends"

    id: str = Field(primary_key=True, index=True)
    title: str = Field(index=True)
    creator: str = Field(default="Autor anónimo")
    platform: str = Field(index=True)  # YouTube, TikTok, LinkedIn
    category: str = Field(default="IA", index=True)
    views: int = Field(default=0)
    likes: int = Field(default=0)
    comments: int = Field(default=0)
    published_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    image: str = Field(default="https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe")
    insight: str = Field(default="Análisis pendiente")
    angle: str = Field(default="Propuesta editorial en desarrollo")
    hook: str = Field(default="Gancho sugerido pendiente")
    audience: str = Field(default="Líderes y equipos en LATAM")
    format: str = Field(default="Video corto + Carrusel")
    source_url: str | None = Field(default=None)
    engagement_score: float = Field(default=0.0, index=True)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_contract(self) -> Trend:
        """Convierte el registro de base de datos al contrato Trend esperado por el frontend."""
        # Normalizar a los literales exactos requeridos por el frontend ('YouTube', 'TikTok', 'LinkedIn')
        plat_lower = self.platform.lower()
        if "you" in plat_lower:
            plat_normalizada = "YouTube"
        elif "tik" in plat_lower:
            plat_normalizada = "TikTok"
        else:
            plat_normalizada = "LinkedIn"

        return Trend(
            id=self.id,
            title=self.title,
            creator=self.creator,
            platform=plat_normalizada,  # type: ignore
            category=self.category,
            views=self.views,
            likes=self.likes,
            comments=self.comments,
            publishedAt=self.published_at,
            image=self.image,
            insight=self.insight,
            angle=self.angle,
            hook=self.hook,
            audience=self.audience,
            format=self.format,
            sourceUrl=self.source_url,
        )


class OpportunityDB(SQLModel, table=True):
    """Registro de oportunidades guardadas, aprobadas o descartadas por el equipo editorial."""

    __tablename__ = "opportunities"

    id: str = Field(primary_key=True, index=True)
    trend_id: str = Field(index=True)
    status: str = Field(default="Pendiente", index=True)  # Pendiente, Aprobada, Descartada
    saved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_contract(self) -> Opportunity:
        return Opportunity(
            id=self.id,
            trendId=self.trend_id,
            status=self.status,  # type: ignore
            savedAt=self.saved_at,
        )


class PublicacionDB(SQLModel, table=True):
    """Registro de publicaciones sin procesar recolectadas por APIs o CSV."""

    __tablename__ = "publicaciones"

    id: str = Field(primary_key=True, index=True)
    schema_version: str = Field(default="1.0")
    plataforma: str = Field(index=True)
    titulo: str | None = Field(default=None)
    texto: str | None = Field(default=None)
    hashtags: str = Field(default="[]")
    formato: str = Field(default="video_corto")
    duracion_segundos: int | None = Field(default=None)
    idioma: str | None = Field(default=None)
    pais: str | None = Field(default=None)
    tipo_autor: str = Field(default="desconocido")
    autor_hash: str = Field(index=True)
    publicada_en: str
    capturada_en: str
    origen: str = Field(default="api_oficial")
    url: str
    views: int = Field(default=0)
    likes: int = Field(default=0)
    comments: int = Field(default=0)


class MetricaDB(SQLModel, table=True):
    """Captura de métricas públicas de una publicación para series de tiempo e historial."""

    __tablename__ = "metricas"

    publicacion_id: str = Field(primary_key=True, index=True)
    capturada_en: str = Field(primary_key=True, index=True)
    vistas: int | None = Field(default=None)
    likes: int | None = Field(default=None)
    comentarios: int | None = Field(default=None)
    compartidos: int | None = Field(default=None)
    origen: str = Field(default="api_oficial")

