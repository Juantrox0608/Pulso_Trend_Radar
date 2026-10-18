"""Offline adapter for the team's metadata and statistics exports. No network."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from pydantic import AwareDatetime, TypeAdapter, ValidationError

from .ranking import calculate_ranking
from .schemas import AnalyzeRequest, Video


def prepare_request(metadata, statistics, limit=5):
    if not isinstance(metadata, list):
        raise ValueError("Los metadatos deben ser una lista")
    if not isinstance(statistics, dict) or not isinstance(statistics.get("stats"), dict):
        raise ValueError("Las estadísticas deben contener un objeto stats")
    if type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError("La muestra debe contener entre 1 y 30 videos")
    try:
        captured = TypeAdapter(AwareDatetime).validate_python(statistics.get("capturada_en"))
    except ValidationError:
        raise ValueError("capturada_en de estadísticas debe ser una fecha con zona horaria") from None
    stats = statistics["stats"]
    counts = Counter(row["id"] for row in metadata if isinstance(row, dict) and isinstance(row.get("id"), str))
    report = {
        "metadata_records": len(metadata), "statistics_records": len(stats),
        "statistics_captured_at": captured.isoformat(),
        "duplicate_metadata_ids": sorted(key for key, count in counts.items() if count > 1),
        "metadata_without_statistics": sorted(set(counts) - set(stats)),
        "statistics_without_metadata": sorted(set(stats) - set(counts)),
        "invalid_records": [], "missing_metric_fields": [],
        "valid_joined_records": 0, "unknown_views_ids": [],
        "selection_method": "Top N among valid joined records with known views; views descending, ID ascending",
        "requested_sample_size": limit,
        "ignored_metadata_fields": sorted({key for row in metadata if isinstance(row, dict) for key in row} - {
            "id", "plataforma", "titulo", "texto", "url", "publicada_en",
        }),
        "notes": [
            "IDs are matched exactly including platform prefix; duplicate IDs are excluded.",
            "author is null: autor_hash is not an author name.",
            "Missing metric keys become null and are reported; zero remains zero.",
            "Invalid records are excluded without truncating texts or coercing metrics.",
            "Only one statistics snapshot is available; no recent growth can be established.",
            "Selection favors accumulated views and is not representative of all YouTube.",
        ],
    }
    valid = []
    for index, row in enumerate(metadata):
        video_id = row.get("id") if isinstance(row, dict) else None
        issue = {"metadata_index": index, "id": video_id if isinstance(video_id, str) else None}
        if not isinstance(video_id, str) or not video_id.startswith("yt:") or len(video_id) <= 3:
            report["invalid_records"].append({**issue, "reason": "invalid_platform_id"})
            continue
        if counts[video_id] > 1:
            continue
        if row.get("plataforma") != "youtube":
            report["invalid_records"].append({**issue, "reason": "unsupported_platform"})
            continue
        if video_id not in stats:
            continue
        metrics = stats[video_id]
        if not isinstance(metrics, dict):
            report["invalid_records"].append({**issue, "reason": "invalid_statistics_record"})
            continue
        missing = [key for key in ("viewCount", "likeCount", "commentCount") if key not in metrics]
        if missing:
            report["missing_metric_fields"].append({"id": video_id, "fields": missing})
        try:
            video = Video.model_validate({
                "id": video_id, "title": row.get("titulo"), "description": row.get("texto"),
                "author": None, "url": row.get("url"), "published_at": row.get("publicada_en"),
                "metrics_collected_at": captured,
                "views": metrics.get("viewCount"), "likes": metrics.get("likeCount"),
                "comments": metrics.get("commentCount"),
            })
        except ValidationError as exc:
            report["invalid_records"].append({**issue, "reason": "schema_validation", "errors": [
                {"location": list(error["loc"]), "type": error["type"]} for error in exc.errors()
            ]})
            continue
        valid.append(video)
    report["valid_joined_records"] = len(valid)
    report["unknown_views_ids"] = sorted(video.id for video in valid if video.views is None)
    known = sorted((v for v in valid if v.views is not None), key=lambda v: (-v.views, v.id))
    selected = known[:limit]
    report["known_views_records"] = len(known)
    report["selected_ids"] = [v.id for v in selected]
    report["selected_count"] = len(selected)
    report["expected_ranking"] = [item.model_dump() for item in calculate_ranking(selected)]
    if not selected:
        return None, report
    request = AnalyzeRequest(
        question=(
            f"Para 30X, analiza únicamente esta selección de {len(selected)} videos con más vistas conocidas "
            f"entre {len(known)} registros válidos unidos de los archivos del equipo. "
            f"Las estadísticas son una sola captura de {captured.isoformat()}. "
            "¿Qué videos destacan dentro de esta selección, qué enfoques sugieren sus metadatos y qué "
            "contenido sobre IA podría producir 30X para su audiencia? Distingue observaciones, hipótesis "
            "y recomendaciones con IDs fuente. Explicita el sesgo de selección por vistas acumuladas; "
            "no afirmes crecimiento reciente, tendencias históricas ni causalidad. "
            "Los nombres de autores no están disponibles: autor_hash no es un nombre."
        ),
        audience="Líderes y equipos de Latinoamérica que están aprendiendo a aplicar inteligencia artificial en su trabajo; audiencia de 30X.",
        videos=selected,
    )
    return request, report


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("El JSON contiene claves duplicadas; no se elige una silenciosamente")
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--statistics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    inputs = {args.metadata.resolve(), args.statistics.resolve()}
    outputs = {args.output.resolve(), args.report.resolve()}
    if inputs & outputs or len(outputs) != 2:
        parser.error("Las salidas deben ser distintas entre sí y de los archivos originales")
    if args.output.exists() or args.report.exists():
        parser.error("Las salidas ya existen; elige nombres nuevos para no sobrescribir archivos")
    try:
        metadata_bytes = args.metadata.read_bytes()
        stats_bytes = args.statistics.read_bytes()
        metadata = json.loads(metadata_bytes.decode("utf-8-sig"), object_pairs_hook=unique_object)
        statistics = json.loads(stats_bytes.decode("utf-8-sig"), object_pairs_hook=unique_object)
        request, report = prepare_request(metadata, statistics, args.limit)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    report["inputs"] = {
        "metadata": {"name": args.metadata.name, "sha256": hashlib.sha256(metadata_bytes).hexdigest()},
        "statistics": {"name": args.statistics.name, "sha256": hashlib.sha256(stats_bytes).hexdigest()},
    }
    serialized = request.model_dump_json(indent=2) if request else None
    if serialized and len(serialized.encode("utf-8")) > 256 * 1024:
        parser.error("La solicitud preparada supera 256 KiB")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if request is None:
        parser.exit(2, "No hay videos válidos con vistas conocidas. Consulta el informe.\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "metadata_records", "statistics_records", "valid_joined_records", "known_views_records", "selected_count", "selected_ids",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
