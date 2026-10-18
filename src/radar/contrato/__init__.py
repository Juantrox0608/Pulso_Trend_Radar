
"""Contrato de datos compartido por los backends y el frontend."""

from radar.contrato.base import Plataforma, calcular_autor_hash
from radar.contrato.metrica import Metrica
from radar.contrato.publicacion import Formato, Origen, Publicacion, TipoAutor
from radar.contrato.urls import id_contrato, id_desde_url, url_canonica
from radar.contrato.trend import (
    Opportunity,
    OpportunityStatus,
    OpportunityUpdate,
    PlataformaFrontend,
    Trend,
)

__all__ = [
    "Formato",
    "Metrica",
    "Opportunity",
    "OpportunityStatus",
    "OpportunityUpdate",
    "Origen",
    "Plataforma",
    "PlataformaFrontend",
    "Publicacion",
    "TipoAutor",
    "Trend",
    "calcular_autor_hash",
    "id_contrato",
    "id_desde_url",
    "url_canonica",
]
