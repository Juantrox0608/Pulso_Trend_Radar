import json
from typing import Protocol

from pydantic import ValidationError

from .errors import ServiceError
from .ranking import calculate_ranking
from .schemas import AnalyzeRequest, AnalyzeResponse, ModelAnalysis


class AnalysisProvider(Protocol):
    async def generate(self, context: str) -> str: ...


async def analyze(request: AnalyzeRequest, provider: AnalysisProvider) -> AnalyzeResponse:
    ranking = calculate_ranking(request.videos)
    context = request.model_dump(mode="json")
    context["ranking"] = [item.model_dump() for item in ranking]
    raw = await provider.generate(json.dumps(context, ensure_ascii=False))
    try:
        interpretation = ModelAnalysis.model_validate_json(raw)
    except (ValidationError, ValueError, TypeError):
        raise ServiceError(502, "invalid_provider_response", "El análisis de Groq no cumple el esquema esperado.") from None
    valid_ids = {video.id for video in request.videos}
    for item in [*interpretation.findings, *interpretation.recommendations]:
        if not set(item.source_video_ids) <= valid_ids:
            raise ServiceError(502, "invalid_source_reference", "El análisis contiene referencias a videos no recibidos.")
    unranked = sorted(v.id for v in request.videos if v.views is None)
    limitations = [
        "El análisis se limita a las publicaciones recibidas y sus metadatos.",
        "No se analizó el contenido audiovisual completo.",
        "No hay historial para establecer crecimiento ni referencia de desempeño del canal.",
        "Las hipótesis no demuestran causalidad.",
    ]
    if unranked:
        limitations.append("Los videos sin visualizaciones conocidas fueron excluidos del ranking.")
    if not ranking:
        limitations.append("No hay visualizaciones conocidas: no es posible comparar desempeño.")
    if len(request.videos) == 1:
        limitations.append("Una sola publicación no permite identificar patrones entre publicaciones.")
    if request.videos[0].platform != "youtube":
        limitations.append("Las métricas desconocidas permanecen null; no equivalen a cero ni son comparables directamente entre plataformas.")
    result = interpretation.model_dump(exclude={"limitations"})
    return AnalyzeResponse(
        **result, ranking=ranking, unranked_video_ids=unranked,
        limitations=list(dict.fromkeys(limitations + interpretation.limitations)),
    )
