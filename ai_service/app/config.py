from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    groq_api_key: SecretStr = SecretStr("")
    # Only these models have been verified for strict structured output.
    groq_model: str = "openai/gpt-oss-20b"
    groq_timeout_seconds: float = Field(default=30, gt=0, le=120)
    groq_max_completion_tokens: int = Field(default=4096, ge=512, le=8192)
