"""Contrato de una publicación: un video de YouTube o TikTok, o un post de LinkedIn."""

from datetime import timezone
from enum import StrEnum

from pydantic import AwareDatetime, Field, computed_field, field_validator, model_validator

from radar.contrato.base import PREFIJO_ID, CodigoIdioma, CodigoPais, ModeloContrato, Plataforma
from radar.contrato.urls import es_id_nativo_valido, url_canonica


class Formato(StrEnum):
    VIDEO_CORTO = "video_corto"
    VIDEO_LARGO = "video_largo"
    POST_TEXTO = "post_texto"
    POST_IMAGEN = "post_imagen"
    CARRUSEL = "carrusel"
    ARTICULO = "articulo"


class TipoAutor(StrEnum):
    EMPRESA = "empresa"
    MEDIO = "medio"
    EXPERTO = "experto"
    CREADOR = "creador"
    INSTITUCION = "institucion"
    DESCONOCIDO = "desconocido"


class Origen(StrEnum):
    API_OFICIAL = "api_oficial"
    CSV_MANUAL = "csv_manual"


class Publicacion(ModeloContrato):
    """Lo que se sabe de una pieza de contenido. Las métricas van aparte, en Metrica.

    La url no se recibe: se arma desde el id en formato canónico, sin usuario ni nombre del autor.
    """

    id: str = Field(pattern=r"^(yt|tt|li):[A-Za-z0-9_\-]+$", examples=["yt:dQw4w9WgXcQ"])
    plataforma: Plataforma
    titulo: str | None = Field(default=None, max_length=300)
    texto: str | None = Field(default=None, max_length=5000)
    hashtags: tuple[str, ...] = ()
    formato: Formato
    duracion_segundos: int | None = Field(default=None, ge=0)
    idioma: CodigoIdioma | None = None
    pais: CodigoPais | None = None
    tipo_autor: TipoAutor = TipoAutor.DESCONOCIDO
    autor_hash: str = Field(pattern=r"^[a-f0-9]{16}$")
    publicada_en: AwareDatetime
    capturada_en: AwareDatetime
    origen: Origen

    @computed_field
    @property
    def url(self) -> str:
        return url_canonica(self.plataforma, self.id_nativo)

    @property
    def id_nativo(self) -> str:
        return self.id.split(":", 1)[1]

    @model_validator(mode="before")
    @classmethod
    def _ignorar_url_recibida(cls, datos: object) -> object:
        """La url siempre se recalcula: así un JSON propio vuelve a validar y nunca entra una url con autor."""
        if isinstance(datos, dict) and "url" in datos:
            return {clave: valor for clave, valor in datos.items() if clave != "url"}
        return datos

    @field_validator("idioma", mode="before")
    @classmethod
    def _normalizar_idioma(cls, valor: object) -> object:
        # YouTube manda "es-419" o "zxx" (sin habla): se guarda solo el idioma base o nada.
        if not isinstance(valor, str):
            return valor
        base = valor.split("-")[0].strip().lower()
        return base if len(base) == 2 and base.isalpha() else None

    @field_validator("pais", mode="before")
    @classmethod
    def _pais_en_mayusculas(cls, valor: object) -> object:
        return valor.strip().upper() if isinstance(valor, str) else valor

    @field_validator("publicada_en", "capturada_en")
    @classmethod
    def _a_utc(cls, valor: AwareDatetime) -> AwareDatetime:
        return valor.astimezone(timezone.utc)

    @field_validator("hashtags")
    @classmethod
    def _normalizar_hashtags(cls, valores: tuple[str, ...]) -> tuple[str, ...]:
        limpios = (v.strip().lstrip("#").lower() for v in valores)
        return tuple(dict.fromkeys(v for v in limpios if v))

    @model_validator(mode="after")
    def _coherencia(self) -> "Publicacion":
        prefijo = PREFIJO_ID[self.plataforma]
        if not self.id.startswith(f"{prefijo}:"):
            raise ValueError(f"El id de {self.plataforma.value} debe empezar con '{prefijo}:'")
        if not es_id_nativo_valido(self.plataforma, self.id_nativo):
            raise ValueError(f"El id no tiene el formato de {self.plataforma.value}: {self.id_nativo}")

        if not (self.titulo or self.texto):
            raise ValueError("La publicación necesita título o texto")

        if self.capturada_en < self.publicada_en:
            raise ValueError("capturada_en no puede ser anterior a publicada_en")
        return self
