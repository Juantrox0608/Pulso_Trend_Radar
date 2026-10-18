from app.errors import ServiceError
from app.ranking import calculate_ranking
from app.schemas import AnalyzeRequest

from .collector_contract import normalize_result
from .errors import CollectionError
from .schemas import CollectionInfo, ResearchResponse, Source, PublicationMetrics


async def research(request, collector, ai, mode="http"):
    data = await collector.collect(request.filters)
    valid, metadata, report = normalize_result(data)
    matching = []
    missing_language = 0
    f = request.filters
    # query and country belong to the remote search, not literal title/author filters.
    for video in valid:
        if video.platform != f.platform:
            continue
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
    selected = known[:f.sample_size] if known else sorted(matching, key=lambda v: v.id)[:f.sample_size]
    if not selected:
        summary = data["resumen"].get(f.platform, {})
        capture = summary.get("detalle", {}) if isinstance(summary, dict) else {}
        capture = capture if isinstance(capture, dict) else {}
        detail = {"service": "collector", "platform": f.platform,
                  "search_id": data.get("search_id"), "metadata_records": report["metadata_records"],
                  "statistics_records": report["statistics_records"],
                  "invalid_records_count": len(report["invalid_records"]), "ai_called": False}
        # Only fixed, non-sensitive counters and flags; never forward provider messages.
        counters = {key: capture[key] for key in ("cuentas", "cuentas_fallidas", "videos", "fuera_fecha", "descartados_tema")
                    if type(capture.get(key)) is int and capture[key] >= 0}
        detail["capture"] = counters
        all_accounts_failed = counters.get("cuentas", 0) > 0 and counters.get("cuentas_fallidas", 0) >= counters["cuentas"]
        stopped = capture.get("detenido") is True
        if report["metadata_records"] == 0 and (all_accounts_failed or stopped):
            detail["reason"] = "capture_failed_or_stopped"
            raise CollectionError(502, "collector_capture_failed",
                "El recolector no pudo capturar publicaciones de esta plataforma. Revisa las cuentas y el acceso del recolector; no se consultó IA.", detail)
        detail["reason"] = "empty_collection" if report["metadata_records"] == 0 else "no_valid_matches"
        raise CollectionError(422, "no_usable_videos", "La búsqueda terminó sin publicaciones válidas que cumplan los filtros; no se consultó IA.", detail)
    note = (
        f" Analiza solo estas {len(selected)} publicaciones de {f.platform}. "
        "La selección no representa toda la plataforma. Cada publicación tiene una captura de métricas: no demuestra crecimiento reciente."
    )
    note += " Selección por vistas conocidas." if known else " No hay vistas conocidas: selección por ID para metadatos, sin ranking de desempeño."
    ai_request = AnalyzeRequest(question=request.question + note, audience=request.audience, videos=selected)
    result = await ai.analyze(ai_request)
    valid_ids = {v.id for v in selected}
    if result.ranking != calculate_ranking(selected) or result.unranked_video_ids != sorted(v.id for v in selected if v.views is None):
        raise ServiceError(502, "ai_invalid_ranking", "La IA devolvió un ranking distinto al esperado.")
    if any(not set(item.source_video_ids) <= valid_ids for item in result.findings + result.recommendations):
        raise ServiceError(502, "ai_invalid_references", "La IA devolvió referencias ajenas a la selección.")
    limitations = [
        "La selección no representa toda la plataforma ni mide crecimiento reciente; métricas ausentes son null, no cero.",
        "Los nombres de autores no están disponibles. Las métricas no son directamente comparables entre plataformas.",
    ]
    limitations.append("Selección por vistas acumuladas conocidas." if known else "Sin vistas conocidas: se muestran métricas disponibles y análisis de metadatos, con ranking vacío.")
    limitations.append("El país es región de búsqueda de YouTube, no ubicación del autor." if f.platform == "youtube" else "El recolector no aplica país a esta plataforma; no se garantiza cobertura del país solicitado.")
    youtube_summary = data["resumen"].get(f.platform, {})
    if isinstance(youtube_summary, dict) and type(youtube_summary.get("fallidas")) is int and youtube_summary["fallidas"] > 0:
        limitations.append("El recolector informó consultas parcialmente fallidas; la cobertura es incompleta.")
    if report["invalid_records"] or report["metadata_without_statistics"] or report["duplicate_metadata_ids"] or report["duplicate_metric_ids"]:
        limitations.append("Se excluyeron registros inválidos, ambiguos o sin estadísticas; consulta el reporte de preparación.")
    result.limitations = list(dict.fromkeys(result.limitations + limitations))
    report.update({"matching_metadata_records": len(matching), "missing_filter_fields_records": missing_language,
                   "selected_ids": [v.id for v in selected], "selected_count": len(selected),
                   "selection_method": "views_desc" if known else "id_asc_no_known_views",
                   "unknown_views_ids": sorted(v.id for v in matching if v.views is None)})
    return ResearchResponse(
        analysis=result,
        sources=[Source(id=v.id, title=v.title, url=str(v.url), platform=v.platform) for v in selected],
        collection=CollectionInfo(mode="http", simulated=False, filters=f, preparation=report),
        metrics=[PublicationMetrics(id=v.id, platform=v.platform, views=v.views, likes=v.likes,
                    comments=v.comments, shares=v.shares, metrics_collected_at=v.metrics_collected_at) for v in selected],
    )
