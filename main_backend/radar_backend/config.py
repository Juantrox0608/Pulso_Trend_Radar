from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8", extra="ignore",
    )
    collector_mode: Literal["mock", "http"] = "mock"
    collector_url: HttpUrl | None = None
    collector_token: SecretStr = SecretStr("")
    collector_timeout_seconds: float = Field(default=10, gt=0, le=120)
    ai_analyze_url: HttpUrl = "http://127.0.0.1:8001/analyze"
    ai_timeout_seconds: float = Field(default=45, gt=0, le=180)
    research_timeout_seconds: float = Field(default=60, gt=0, le=240)
    cors_origins: list[str] = Field(default_factory=list)

    @field_validator("collector_url", mode="before")
    @classmethod
    def optional_collector_url(cls, value):
        return None if value == "" else value
