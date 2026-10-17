"""Tipos y convenciones comunes del contrato de datos del radar."""

import hashlib
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

VERSION_CONTRATO = "1.0"


class Plataforma(StrEnum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    LINKEDIN = "linkedin"


PREFIJO_ID: dict[Plataforma, str] = {
    Plataforma.YOUTUBE: "yt",
    Plataforma.TIKTOK: "tt",
    Plataforma.LINKEDIN: "li",
}

CodigoPais = Annotated[str, Field(pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alfa-2, ej. MX")]
CodigoIdioma = Annotated[str, Field(pattern=r"^[a-z]{2}$", description="ISO 639-1, ej. es")]


class ModeloContrato(BaseModel):
    """Base de todos los objetos del contrato: inmutables, sin campos extra y versionados."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1.0"] = VERSION_CONTRATO


def calcular_autor_hash(plataforma: Plataforma, id_autor: str, sal: str) -> str:
    """Seudónimo estable del autor: permite contar autores distintos sin guardar quién es."""
    if not sal:
        raise ValueError("La sal del hash de autor no puede estar vacía")
    crudo = f"{sal}:{plataforma.value}:{id_autor}".encode()
    return hashlib.sha256(crudo).hexdigest()[:16]
