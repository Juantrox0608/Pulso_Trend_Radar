from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8", extra="ignore",
    )
    collector_mode: Literal["http"] = "http"
    collector_url: HttpUrl = "https://radar-recoleccion.onrender.com"
    collector_timeout_seconds: float = Field(default=30, gt=0, le=120)
    collector_search_timeout_seconds: float = Field(default=150, gt=0, le=600)
    collector_poll_interval_seconds: float = Field(default=2, gt=0, le=30)
    collector_default_days: int = Field(default=7, ge=1, le=36500)
    collector_default_country: str = Field(default="CO", pattern=r"^[A-Z]{2}$")
    ai_analyze_url: HttpUrl = "http://127.0.0.1:8001/analyze"
    ai_timeout_seconds: float = Field(default=45, gt=0, le=180)
    research_timeout_seconds: float = Field(default=210, gt=0, le=900)
    cors_origins: list[str] = Field(default_factory=list)

    @field_validator("collector_url", mode="before")
    @classmethod
    def optional_collector_url(cls, value):
        return "https://radar-recoleccion.onrender.com" if value == "" else value
