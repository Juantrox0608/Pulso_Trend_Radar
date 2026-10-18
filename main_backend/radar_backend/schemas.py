from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator
from app.schemas import AnalyzeResponse, Schema, Metric

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Filters(Schema):
    query: ShortText
    platform: Literal["youtube", "tiktok", "linkedin"] = "youtube"
    language: Annotated[str, StringConstraints(pattern=r"^[a-z]{2}$")] | None = None
    country: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")] | None = None
    published_after: AwareDatetime | None = None
    published_before: AwareDatetime | None = None
    sample_size: int = Field(default=5, ge=1, le=10, strict=True)

    @model_validator(mode="after")
    def dates(self):
        if self.published_after and self.published_before and self.published_after > self.published_before:
            raise ValueError("El inicio no puede ser posterior al fin")
        return self


class ResearchRequest(Schema):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1500)]
    audience: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    filters: Filters


class Source(Schema):
    id: str
    title: str | None
    url: str
    platform: Literal["youtube", "tiktok", "linkedin"] = "youtube"


class PublicationMetrics(Schema):
    id: str
    platform: Literal["youtube", "tiktok", "linkedin"]
    views: Metric | None
    likes: Metric | None
    comments: Metric | None
    shares: Metric | None
    metrics_collected_at: AwareDatetime


class CollectionInfo(Schema):
    mode: Literal["http"]
    simulated: bool
    filters: Filters
    preparation: dict


class ResearchResponse(Schema):
    analysis: AnalyzeResponse
    sources: list[Source]
    collection: CollectionInfo
    metrics: list[PublicationMetrics] = Field(default_factory=list)
