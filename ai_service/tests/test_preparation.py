import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.prepare_request import prepare_request, unique_object
from app.ranking import calculate_ranking
from app.schemas import AnalyzeRequest, AnalyzeResponse


@pytest.fixture
def exports():
    metadata = [{
        "id": f"yt:{name}", "plataforma": "youtube", "titulo": f"FICTICIO {name}",
        "texto": None, "autor_hash": "not-a-name", "url": f"https://youtu.be/{name}",
        "publicada_en": "2026-10-10T00:00:00Z", "capturada_en": "2026-10-11T00:00:00Z",
    } for name in ("a", "b", "c", "d")]
    statistics = {"capturada_en": "2026-10-17T06:42:53.022937+00:00", "stats": {
        "yt:a": {"viewCount": 100, "likeCount": 0, "commentCount": None},
        "yt:b": {"viewCount": 100, "likeCount": None, "commentCount": 0},
        "yt:c": {"viewCount": 0, "likeCount": 0, "commentCount": 0},
        "yt:d": {"viewCount": None, "likeCount": None, "commentCount": None},
    }}
    return metadata, statistics


def test_join_exact_ids_capture_null_zero_and_no_mutation(exports):
    metadata, stats = exports
    before = copy.deepcopy(exports)
    request, report = prepare_request(metadata, stats, 5)
    assert exports == before
    assert [v.id for v in request.videos] == ["yt:a", "yt:b", "yt:c"]
    assert request.videos[0].likes == 0
    assert request.videos[0].comments is None
    assert request.videos[1].likes is None
    assert request.videos[2].views == 0
    assert all(v.author is None for v in request.videos)
    assert all(v.metrics_collected_at.isoformat() == stats["capturada_en"] for v in request.videos)
    assert report["unknown_views_ids"] == ["yt:d"]
    assert [r.position for r in calculate_ranking(request.videos)] == [1, 1, 3]


def test_unmatched_and_duplicate_ids(exports):
    metadata, stats = exports
    metadata.append(copy.deepcopy(metadata[0]))
    del stats["stats"]["yt:b"]
    stats["stats"]["tt:c"] = stats["stats"]["yt:c"]
    request, report = prepare_request(metadata, stats)
    assert report["duplicate_metadata_ids"] == ["yt:a"]
    assert report["metadata_without_statistics"] == ["yt:b"]
    assert report["statistics_without_metadata"] == ["tt:c"]
    assert [v.id for v in request.videos] == ["yt:c"]


@pytest.mark.parametrize("value", [-1, True, "100", 1.5])
def test_bad_metrics_reported_not_coerced(exports, value):
    metadata, stats = exports
    stats["stats"]["yt:a"]["viewCount"] = value
    request, report = prepare_request(metadata, stats)
    assert "yt:a" not in [v.id for v in request.videos]
    assert report["invalid_records"][0]["id"] == "yt:a"


def test_missing_metric_fields_become_null_with_report(exports):
    metadata, stats = exports
    del stats["stats"]["yt:a"]["likeCount"]
    request, report = prepare_request(metadata, stats)
    assert request.videos[0].likes is None
    assert report["missing_metric_fields"] == [{"id": "yt:a", "fields": ["likeCount"]}]


@pytest.mark.parametrize("change", ["long_description", "naive_publication", "wrong_platform", "bad_stats", "missing_id"])
def test_invalid_records_are_reported(exports, change):
    metadata, stats = exports
    if change == "long_description":
        metadata[0]["texto"] = "x" * 5001
    elif change == "naive_publication":
        metadata[0]["publicada_en"] = "2026-10-10T00:00:00"
    elif change == "wrong_platform":
        metadata[0]["plataforma"] = "linkedin"
    elif change == "bad_stats":
        stats["stats"]["yt:a"] = None
    else:
        del metadata[0]["id"]
    request, report = prepare_request(metadata, stats)
    assert len(report["invalid_records"]) == 1
    assert "yt:a" not in [v.id for v in request.videos]


@pytest.mark.parametrize("capture", [None, "invalid", "2026-10-17T06:00:00"])
def test_bad_capture_rejected(exports, capture):
    metadata, stats = exports
    stats["capturada_en"] = capture
    with pytest.raises(ValueError):
        prepare_request(metadata, stats)


def test_earlier_capture_invalidates_videos(exports):
    metadata, stats = exports
    stats["capturada_en"] = "2020-01-01T00:00:00Z"
    request, report = prepare_request(metadata, stats)
    assert request is None
    assert len(report["invalid_records"]) == 4


def test_no_known_views_produces_report_without_request(exports):
    metadata, stats = exports
    for row in stats["stats"].values():
        row["viewCount"] = None
    request, report = prepare_request(metadata, stats)
    assert request is None
    assert report["selected_count"] == 0


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError):
        json.loads('{"yt:a":{},"yt:a":{}}', object_pairs_hook=unique_object)


def test_cli_preserves_originals_and_protects_paths(exports, tmp_path):
    metadata, stats = exports
    m, s = tmp_path / "metadata.json", tmp_path / "stats.json"
    m.write_text(json.dumps(metadata), encoding="utf-8")
    s.write_text(json.dumps(stats), encoding="utf-8")
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (m, s)]
    output, report = tmp_path / "request.json", tmp_path / "report.json"
    command = [sys.executable, "-m", "app.prepare_request", "--metadata", str(m),
               "--statistics", str(s), "--output", str(output), "--report", str(report)]
    result = subprocess.run(command, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert len(AnalyzeRequest.model_validate_json(output.read_text()).videos) == 3
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in (m, s)]
    assert subprocess.run(command, capture_output=True).returncode != 0
    command[command.index("--output") + 1] = str(m)
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in (m, s)]


def test_generated_real_sample_through_endpoint_without_network():
    examples = Path(__file__).parents[1] / "examples"
    body = json.loads((examples / "analyze_real_top5_2026-10-17.json").read_text(encoding="utf-8"))
    report = json.loads((examples / "preparation_report_2026-10-17.json").read_text(encoding="utf-8"))
    request = AnalyzeRequest.model_validate(body)
    assert len(request.videos) == 5
    assert [r.model_dump() for r in calculate_ranking(request.videos)] == report["expected_ranking"]

    class Fake:
        async def generate(self, context):
            data = json.loads(context)
            assert len(data["videos"]) == 5
            source = data["videos"][0]["id"]
            return json.dumps({
                "summary": "Respuesta simulada de prueba de integración; no es análisis real.",
                "findings": [{"observation": "Hay metadatos disponibles.", "hypothesis": None, "source_video_ids": [source]}],
                "recommendations": [{"title": "Ejemplo de prueba", "suggested_format": "Tutorial",
                                     "reason": "Demostración para 30X", "source_video_ids": [source]}],
                "limitations": ["Solo selección por vistas acumuladas; no mide crecimiento reciente."],
            })

    with TestClient(create_app(Fake())) as client:
        response = client.post("/analyze", json=body)
    assert response.status_code == 200
    result = AnalyzeResponse.model_validate(response.json())
    assert result.ranking and result.summary and result.findings and result.recommendations and result.limitations
    ids = {v.id for v in request.videos}
    assert all(set(item.source_video_ids) <= ids for item in result.findings + result.recommendations)
    assert any("historial" in text for text in result.limitations)
