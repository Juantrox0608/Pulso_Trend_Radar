"""Modelos del contrato con el frontend para tendencias y oportunidades editoriales."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


PlataformaFrontend = Literal["YouTube", "TikTok", "LinkedIn"]
OpportunityStatus = Literal["Pendiente", "Aprobada", "Descartada"]


class Trend(BaseModel):
    """Modelo de tendencia enviado al frontend. Corresponde al tipo Trend de Next.js."""

    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    creator: str
    platform: PlataformaFrontend
    category: str
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    publishedAt: str
    image: str
    insight: str
    angle: str
    hook: str
    audience: str
    format: str
    sourceUrl: str | None = None


class Opportunity(BaseModel):
    """Modelo de oportunidad editorial guardada."""

    model_config = ConfigDict(extra="ignore")

    id: str
    trendId: str
    status: OpportunityStatus = "Pendiente"
    savedAt: str


class OpportunityUpdate(BaseModel):
    """Payload para actualizar el estado de una oportunidad."""

    status: OpportunityStatus
