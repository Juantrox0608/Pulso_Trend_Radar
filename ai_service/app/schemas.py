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
    id: VideoId
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    description: Annotated[str, StringConstraints(max_length=5000)] | None = None
    author: Annotated[str, StringConstraints(max_length=300)] | None = None
    url: HttpUrl
    published_at: AwareDatetime
    metrics_collected_at: AwareDatetime
    views: Metric | None
    likes: Metric | None
    comments: Metric | None

    @field_validator("url")
    @classmethod
    def youtube_url(cls, value):
        if value.scheme != "https" or value.host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
            raise ValueError("Se requiere una URL HTTPS de YouTube")
        return value

    @model_validator(mode="after")
    def chronological(self):
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
