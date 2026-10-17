"""Una captura de las métricas públicas de una publicación."""
from datetime import timezone
from typing import Annotated

from pydantic import AwareDatetime, Field, field_validator, model_validator

from radar.contrato.base import ModeloContrato
from radar.contrato.publicacion import Origen

Conteo = Annotated[int, Field(ge=0, strict=True)]


class Metrica(ModeloContrato):
    publicacion_id: str = Field(pattern=r"^(yt|tt|li):[A-Za-z0-9_\-]+$")
    capturada_en: AwareDatetime
    vistas: Conteo | None = None
    likes: Conteo | None = None
    comentarios: Conteo | None = None
    compartidos: Conteo | None = None
    origen: Origen

    @field_validator("capturada_en")
    @classmethod
    def _a_utc(cls, valor: AwareDatetime) -> AwareDatetime:
        return valor.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _alguna_metrica(self) -> "Metrica":
        if all(v is None for v in (self.vistas, self.likes, self.comentarios, self.compartidos)):
            raise ValueError("La captura necesita al menos una métrica con valor")
        return self
