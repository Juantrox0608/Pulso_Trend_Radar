from app.errors import ServiceError
from app.ranking import calculate_ranking
from app.schemas import AnalyzeRequest

from .collector_contract import normalize_result
from .schemas import CollectionInfo, ResearchResponse, Source


async def research(request, collector, ai, mode="http"):
    data = await collector.collect(request.filters)
    valid, metadata, report = normalize_result(data)
    matching = []
    missing_language = 0
    f = request.filters
    # query and country belong to the remote search, not literal title/author filters.
    for video in valid:
        row = metadata[video.id]
        if f.language and not row.get("idioma"):
            missing_language += 1
            continue
        if f.language and row.get("idioma") != f.language:
            continue
        if f.published_after and video.published_at < f.published_after:
            continue
        if f.published_before and video.published_at > f.published_before:
            continue
        matching.append(video)
    known = sorted((v for v in matching if v.views is not None), key=lambda v: (-v.views, v.id))
    selected = known[:f.sample_size]
    if not selected:
        raise ServiceError(422, "no_usable_videos", "La búsqueda terminó sin videos válidos con vistas conocidas que cumplan los filtros; no se consultó IA.")
    note = (
        f" Analiza solo estos {len(selected)} videos seleccionados por vistas acumuladas conocidas. "
        "La selección no representa todo YouTube. Cada video tiene una captura de métricas: no demuestra crecimiento reciente."
    )
    ai_request = AnalyzeRequest(question=request.question + note, audience=request.audience, videos=selected)
    result = await ai.analyze(ai_request)
    valid_ids = {v.id for v in selected}
    if result.ranking != calculate_ranking(selected) or result.unranked_video_ids != []:
        raise ServiceError(502, "ai_invalid_ranking", "La IA devolvió un ranking distinto al esperado.")
    if any(not set(item.source_video_ids) <= valid_ids for item in result.findings + result.recommendations):
        raise ServiceError(502, "ai_invalid_references", "La IA devolvió referencias ajenas a la selección.")
    limitations = [
        "Selección por visualizaciones acumuladas conocidas; no representa todo YouTube ni mide crecimiento reciente.",
        "El país es la región de búsqueda, no la ubicación del autor. Los nombres de autores no están disponibles.",
    ]
    youtube_summary = data["resumen"].get("youtube", {})
    if isinstance(youtube_summary, dict) and type(youtube_summary.get("fallidas")) is int and youtube_summary["fallidas"] > 0:
        limitations.append("El recolector informó consultas parcialmente fallidas; la cobertura es incompleta.")
    if report["invalid_records"] or report["metadata_without_statistics"] or report["duplicate_metadata_ids"] or report["duplicate_metric_ids"]:
        limitations.append("Se excluyeron registros inválidos, ambiguos o sin estadísticas; consulta el reporte de preparación.")
    result.limitations = list(dict.fromkeys(result.limitations + limitations))
    report.update({"matching_metadata_records": len(matching), "missing_filter_fields_records": missing_language,
                   "selected_ids": [v.id for v in selected], "selected_count": len(selected),
                   "unknown_views_ids": sorted(v.id for v in matching if v.views is None)})
    return ResearchResponse(
        analysis=result,
        sources=[Source(id=v.id, title=v.title, url=str(v.url)) for v in selected],
        collection=CollectionInfo(mode="http", simulated=False, filters=f, preparation=report),
    )
