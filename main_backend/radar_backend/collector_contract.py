"""Adapter verified against recoleccion/servicio.py and contrato/metrica.py."""
from collections import Counter
from datetime import datetime, timezone
from math import ceil
import unicodedata

from pydantic import ValidationError
from app.errors import ServiceError
from app.schemas import Video


def collector_parameters(filters, settings, now=None):
    now = now or datetime.now(timezone.utc)
    terms = list(dict.fromkeys(part.strip().casefold() for part in filters.query.split(",") if part.strip()))
    if not 1 <= len(terms) <= 5 or any(
        term.startswith("#") and not "".join(c for c in unicodedata.normalize("NFKD", term.lstrip("#")) if not unicodedata.combining(c))
        for term in terms
    ):
        raise ServiceError(422, "invalid_collector_filters", "query requiere de uno a cinco términos distintos y hashtags con texto.")
    days = settings.collector_default_days
    if filters.published_after:
        delta = (now - filters.published_after).total_seconds()
        if delta < 0 or delta > 36500 * 86400:
            raise ServiceError(422, "invalid_collector_filters", "published_after debe estar en el pasado y dentro de 36500 días.")
        # One extra day makes the remote cutoff a superset despite clock/queue drift.
        days = min(36500, max(1, ceil(delta / 86400) + 1))
    return {"tema": filters.query, "redes": [filters.platform], "dias": days,
            "paises": [filters.country or settings.collector_default_country]}


def normalize_result(data):
    if (not isinstance(data, dict) or data.get("estado") != "lista"
            or not isinstance(data.get("publicaciones"), list) or not isinstance(data.get("metricas"), list)
            or not isinstance(data.get("resumen"), dict)):
        raise ServiceError(502, "collector_invalid_response", "Resultado inválido: se requieren publicaciones, metricas y resumen.")
    publications, metrics = data["publicaciones"], data["metricas"]
    if len(publications) > 2000 or len(metrics) > 2000:
        raise ServiceError(502, "collector_too_many_records", "El recolector excedió 2000 publicaciones o métricas.")
    def ids(rows, field):
        return Counter(row[field] for row in rows if isinstance(row, dict) and isinstance(row.get(field), str))
    pids, mids = ids(publications, "id"), ids(metrics, "publicacion_id")
    report = {
        "metadata_records": len(publications), "statistics_records": len(metrics),
        "duplicate_metadata_ids": sorted(k for k, n in pids.items() if n > 1),
        "duplicate_metric_ids": sorted(k for k, n in mids.items() if n > 1),
        "metadata_without_statistics": sorted(pids.keys() - mids.keys()),
        "statistics_without_metadata": sorted(mids.keys() - pids.keys()),
        "invalid_records": [], "missing_metric_fields": [], "statistics_captured_at_by_id": {},
        "search_id": data.get("search_id"), "collector_parameters": data.get("request_parameters"),
    }
    indexed = {}
    for index, metric in enumerate(metrics):
        mid = metric.get("publicacion_id") if isinstance(metric, dict) else None
        if not isinstance(mid, str) or not mid.startswith("yt:"):
            report["invalid_records"].append({"metric_index": index, "reason": "invalid_metric_id"})
        elif mids[mid] == 1:
            indexed[mid] = metric
    valid = []
    metadata_by_id = {}
    for index, row in enumerate(publications):
        pid = row.get("id") if isinstance(row, dict) else None
        issue = {"metadata_index": index, "id": pid if isinstance(pid, str) else None}
        if not isinstance(pid, str) or not pid.startswith("yt:") or len(pid) <= 3 or row.get("plataforma") != "youtube":
            report["invalid_records"].append({**issue, "reason": "unsupported_platform_or_id"})
            continue
        if pids[pid] > 1 or mids[pid] > 1 or pid not in indexed:
            continue
        metric = indexed[pid]
        try:
            video = Video.model_validate({
                "id": pid, "title": row.get("titulo"), "description": row.get("texto"), "author": None,
                "url": row.get("url"), "published_at": row.get("publicada_en"),
                "metrics_collected_at": metric.get("capturada_en"),
                "views": metric.get("vistas"), "likes": metric.get("likes"), "comments": metric.get("comentarios"),
            })
        except ValidationError as exc:
            report["invalid_records"].append({**issue, "reason": "schema_validation", "errors": [
                {"location": list(e["loc"]), "type": e["type"]} for e in exc.errors()
            ]})
            continue
        missing = [key for key in ("vistas", "likes", "comentarios") if key not in metric]
        if missing:
            report["missing_metric_fields"].append({"id": pid, "fields": missing})
        valid.append(video)
        metadata_by_id[pid] = row
        report["statistics_captured_at_by_id"][pid] = video.metrics_collected_at.isoformat()
    report["valid_joined_records"] = len(valid)
    return valid, metadata_by_id, report
