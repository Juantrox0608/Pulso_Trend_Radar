from pydantic import TypeAdapter, AwareDatetime, ValidationError

from app.errors import ServiceError
from app.prepare_request import prepare_request
from app.ranking import calculate_ranking
from app.schemas import AnalyzeRequest

from .schemas import CollectionInfo, ResearchResponse, Source


async def research(request, collector, ai, mode):
    data = await collector.collect(request.filters)
    if not isinstance(data, dict) or not isinstance(data.get("metadata"), list) or not isinstance(data.get("statistics"), dict):
        raise ServiceError(502, "collector_invalid_response", "Se requieren metadata y statistics del recolector.")
    if len(data["metadata"]) > 2000:
        raise ServiceError(502, "collector_too_many_records", "El recolector excedió 2000 registros; acuerda paginación.")
    # Validate/join before filtering so malformed rows remain visible in the report.
    try:
        _, original_report = prepare_request(data["metadata"], data["statistics"], request.filters.sample_size)
    except (ValueError, TypeError, KeyError):
        raise ServiceError(502, "collector_invalid_response", "El recolector devolvió una estructura o captura inválida.") from None
    invalid = {issue["metadata_index"] for issue in original_report["invalid_records"]}
    duplicates = set(original_report["duplicate_metadata_ids"])
    selected_metadata = []
    missing_filter_fields = 0
    f = request.filters
    for index, row in enumerate(data["metadata"]):
        if index in invalid or row.get("id") in duplicates:
            continue
        if f.query.casefold() not in f"{row.get('titulo', '')} {row.get('texto') or ''}".casefold():
            continue
        if (f.language and not row.get("idioma")) or (f.country and not row.get("pais")):
            missing_filter_fields += 1
            continue
        if f.language and row.get("idioma") != f.language:
            continue
        if f.country and row.get("pais") != f.country:
            continue
        try:
            published = TypeAdapter(AwareDatetime).validate_python(row.get("publicada_en"))
        except ValidationError:
            continue
        if f.published_after and published < f.published_after:
            continue
        if f.published_before and published > f.published_before:
            continue
        selected_metadata.append(row)
    try:
        prepared, report = prepare_request(selected_metadata, data["statistics"], f.sample_size)
    except (ValueError, TypeError, KeyError):
        raise ServiceError(502, "collector_invalid_response", "No se pudieron preparar los datos del recolector.") from None
    if prepared is None:
        raise ServiceError(422, "no_usable_videos", "No hay videos válidos con vistas conocidas que cumplan los filtros.")
    note = (
        f" Analiza solo estos {len(prepared.videos)} videos seleccionados por vistas acumuladas conocidas. "
        "La selección no representa todo YouTube. Solo hay una captura de métricas: no demuestra crecimiento reciente."
    )
    if mode == "mock":
        note += " DATOS FICTICIOS: prueba de integración, no evidencia de mercado."
    ai_request = AnalyzeRequest(question=request.question + note, audience=request.audience, videos=prepared.videos)
    result = await ai.analyze(ai_request)
    valid_ids = {v.id for v in prepared.videos}
    if result.ranking != calculate_ranking(prepared.videos) or result.unranked_video_ids != []:
        raise ServiceError(502, "ai_invalid_ranking", "La IA devolvió un ranking distinto al esperado.")
    if any(not set(item.source_video_ids) <= valid_ids for item in result.findings + result.recommendations):
        raise ServiceError(502, "ai_invalid_references", "La IA devolvió referencias ajenas a la selección.")
    result.limitations = list(dict.fromkeys(result.limitations + [
        "Selección por visualizaciones acumuladas conocidas; no representa todo YouTube ni mide crecimiento reciente.",
    ] + (["DATOS SIMULADOS: resultados de demostración sin evidencia real de mercado."] if mode == "mock" else [])))
    summary = {key: original_report[key] for key in (
        "metadata_records", "statistics_records", "duplicate_metadata_ids", "metadata_without_statistics",
        "statistics_without_metadata", "invalid_records", "missing_metric_fields", "statistics_captured_at",
    )}
    summary.update({"matching_metadata_records": len(selected_metadata),
                    "missing_filter_fields_records": missing_filter_fields,
                    "selected_ids": report["selected_ids"], "selected_count": report["selected_count"],
                    "unknown_views_ids": report["unknown_views_ids"]})
    return ResearchResponse(
        analysis=result,
        sources=[Source(id=v.id, title=v.title, url=str(v.url)) for v in prepared.videos],
        collection=CollectionInfo(mode=mode, simulated=mode == "mock", filters=f, preparation=summary),
    )
