from typing import Annotated, Literal

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, StringConstraints,
    field_validator, model_validator,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
VideoId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Metric = Annotated[int, Field(strict=True, ge=0)]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Video(Schema):
    platform: Literal["youtube", "tiktok", "linkedin"] = "youtube"
    id: VideoId
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None
    description: Annotated[str, StringConstraints(max_length=5000)] | None = None
    author: Annotated[str, StringConstraints(max_length=300)] | None = None
    url: HttpUrl
    published_at: AwareDatetime
    metrics_collected_at: AwareDatetime
    views: Metric | None
    likes: Metric | None
    comments: Metric | None
    shares: Metric | None = None

    @model_validator(mode="before")
    @classmethod
    def infer_platform(cls, data):
        if isinstance(data, dict) and "platform" not in data:
            prefix = str(data.get("id", "")).split(":", 1)[0]
            platform = {"yt": "youtube", "tt": "tiktok", "li": "linkedin"}.get(prefix)
            if platform:
                return {**data, "platform": platform}
        return data

    @field_validator("url")
    @classmethod
    def platform_url(cls, value, info):
        hosts = {
            "youtube": {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"},
            "tiktok": {"tiktok.com", "www.tiktok.com", "m.tiktok.com"},
            "linkedin": {"linkedin.com", "www.linkedin.com", "lnkd.in"},
        }
        if value.scheme != "https" or value.host not in hosts.get(info.data.get("platform", "youtube"), set()):
            raise ValueError("Se requiere una URL HTTPS de la plataforma indicada")
        return value

    @model_validator(mode="after")
    def chronological(self):
        expected = {"youtube": "yt:", "tiktok": "tt:", "linkedin": "li:"}[self.platform]
        if (":" in self.id and not self.id.startswith(expected)) or (self.platform != "youtube" and not self.id.startswith(expected)):
            raise ValueError("El prefijo del ID no coincide con la plataforma")
        if self.platform == "youtube" and not self.title:
            raise ValueError("Los videos de YouTube requieren título")
        if not self.title and not (self.description and self.description.strip()):
            raise ValueError("La publicación requiere título o texto")
        if self.metrics_collected_at < self.published_at:
            raise ValueError("Las métricas no pueden preceder a la publicación")
        return self


class AnalyzeRequest(Schema):
    question: Text
    audience: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    videos: list[Video] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({v.id for v in self.videos}) != len(self.videos):
            raise ValueError("Los IDs de video deben ser únicos")
        if len({video.platform for video in self.videos}) > 1:
            raise ValueError("Analiza una plataforma por solicitud; las métricas entre redes no son directamente comparables")
        return self


class RankingItem(Schema):
    video_id: VideoId
    position: int = Field(ge=1)
    metric: Literal["views"] = "views"
    value: Metric


class Finding(Schema):
    observation: Text
    hypothesis: Text | None
    source_video_ids: list[VideoId] = Field(min_length=1, max_length=30)


class Recommendation(Schema):
    title: Text
    suggested_format: Text
    reason: Text
    source_video_ids: list[VideoId] = Field(min_length=1, max_length=30)


class ModelAnalysis(Schema):
    summary: Text
    findings: list[Finding] = Field(max_length=10)
    recommendations: list[Recommendation] = Field(max_length=10)
    limitations: list[Text] = Field(max_length=10)


class AnalyzeResponse(ModelAnalysis):
    ranking: list[RankingItem]
    ranking_method: Literal["views_desc"] = "views_desc"
    unranked_video_ids: list[VideoId]
    analysis_mode: Literal["groq"] = "groq"
    # Includes mandatory service limitations in addition to model limitations.
    limitations: list[Text]


class ErrorInfo(Schema):
    code: str
    message: str
    details: list[dict] = Field(default_factory=list)


class ErrorResponse(Schema):
    error: ErrorInfo
