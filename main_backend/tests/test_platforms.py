import asyncio
import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.schemas import AnalyzeRequest
from app.main import create_app as create_ai_app
from app.ranking import calculate_ranking
from radar_backend.clients import AIClient
from radar_backend.collector_contract import collector_parameters, normalize_result
from radar_backend.config import Settings
from radar_backend.main import create_app
from radar_backend.schemas import Filters


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    async def blocked(*args, **kwargs):
        raise AssertionError("External network forbidden")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)


def fixture(platform):
    prefix = {"youtube": "yt", "tiktok": "tt", "linkedin": "li"}[platform]
    urls = {"youtube": "https://www.youtube.com/watch?v=abc123", "tiktok": "https://www.tiktok.com/@/video/1234567890123456789",
            "linkedin": "https://www.linkedin.com/feed/update/urn:li:activity:1234567890123456789/"}
    return {"estado": "lista", "resumen": {platform: {"fallidas": 0}},
        "publicaciones": [{"id": prefix + ":1234567890123456789", "plataforma": platform,
            "titulo": None if platform == "linkedin" else "FICTICIO: IA", "texto": "Texto ficticio para pruebas",
            "url": urls[platform], "autor_hash": "not-a-name", "publicada_en": "2026-10-15T12:00:00Z"}],
        "metricas": [{"publicacion_id": prefix + ":1234567890123456789", "capturada_en": "2026-10-17T12:00:00Z",
            "vistas": None if platform == "linkedin" else 0, "likes": 12, "comentarios": 0, "compartidos": None}]}


@pytest.mark.parametrize("platform", ["youtube", "tiktok", "linkedin"])
def test_platform_roundtrip_with_real_ai_app(platform):
    data = fixture(platform)
    original = copy.deepcopy(data)
    settings = Settings(_env_file=None)
    assert collector_parameters(Filters(query="IA", platform=platform), settings)["redes"] == [platform]

    class Collector:
        async def collect(self, filters):
            return data

    class Model:
        async def generate(self, context):
            parsed = json.loads(context)
            assert parsed["videos"][0]["platform"] == platform
            assert parsed["videos"][0]["shares"] is None
            source = parsed["videos"][0]["id"]
            return json.dumps({"summary": "Prueba sin red", "findings": [{"observation": "Hay texto disponible",
                "hypothesis": None, "source_video_ids": [source]}], "recommendations": [], "limitations": []})

    with TestClient(create_ai_app(Model())) as ai_server:
        def handler(request):
            response = ai_server.post("/analyze", json=json.loads(request.content))
            return httpx.Response(response.status_code, json=response.json())
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with TestClient(create_app(settings, Collector(), AIClient(settings, http))) as client:
                response = client.post("/research", json={"question": "¿Qué producir?", "audience": "Equipos LATAM",
                    "filters": {"query": "IA", "platform": platform, "sample_size": 1}})
            assert response.status_code == 200, response.text
            result = response.json()
            metric = result["metrics"][0]
            assert metric["platform"] == platform and metric["likes"] == 12
            assert metric["comments"] == 0 and metric["shares"] is None
            assert result["sources"][0]["platform"] == platform
            if platform == "linkedin":
                assert metric["views"] is None
                assert result["sources"][0]["title"] is None
                assert result["analysis"]["ranking"] == []
                assert result["analysis"]["unranked_video_ids"] == [metric["id"]]
                assert result["collection"]["preparation"]["selection_method"] == "id_asc_no_known_views"
            else:
                assert result["analysis"]["ranking"][0]["value"] == 0
            assert data == original
        finally:
            asyncio.run(http.aclose())


def test_infers_platform_from_prefixed_id():
    videos, _, _ = normalize_result(fixture("tiktok"))
    raw = videos[0].model_dump(mode="json")
    del raw["platform"]
    request = AnalyzeRequest(question="Test", audience="Test", videos=[raw])
    assert request.videos[0].platform == "tiktok"


@pytest.mark.parametrize("mutation", ["wrong_host", "suffix_host", "prefix", "empty_text", "negative_share", "string_share"])
def test_invalid_cross_platform_records_rejected(mutation):
    data = fixture("linkedin")
    row, metric = data["publicaciones"][0], data["metricas"][0]
    if mutation == "wrong_host":
        row["url"] = "https://www.youtube.com/watch?v=abc123"
    elif mutation == "suffix_host":
        row["url"] = "https://linkedin.com.evil.example/post"
    elif mutation == "prefix":
        row["id"] = metric["publicacion_id"] = "tt:1234567890123456789"
    elif mutation == "empty_text":
        row["texto"] = None
    elif mutation == "negative_share":
        metric["compartidos"] = -1
    else:
        metric["compartidos"] = "10"
    videos, _, report = normalize_result(data)
    assert videos == [] and report["invalid_records"]


def test_linkedin_short_link_and_known_shares():
    data = fixture("linkedin")
    data["publicaciones"][0]["url"] = "https://lnkd.in/d/abcd1234"
    data["metricas"][0]["compartidos"] = 0
    videos, _, _ = normalize_result(data)
    assert videos[0].shares == 0 and videos[0].views is None


def test_mixed_platform_analysis_rejected():
    youtube, _, _ = normalize_result(fixture("youtube"))
    linkedin, _, _ = normalize_result(fixture("linkedin"))
    with pytest.raises(ValidationError):
        AnalyzeRequest(question="Test", audience="Test", videos=youtube + linkedin)


def test_no_invented_score_when_no_views():
    videos, _, _ = normalize_result(fixture("linkedin"))
    assert videos[0].likes == 12 and calculate_ranking(videos) == []


@pytest.mark.parametrize("name,platform", [("research_linkedin.json", "linkedin"), ("research_tiktok.json", "tiktok")])
def test_postman_examples(name, platform):
    from pathlib import Path
    from radar_backend.schemas import ResearchRequest
    path = Path(__file__).parents[1] / "examples" / name
    request = ResearchRequest.model_validate_json(path.read_text(encoding="utf-8"))
    assert request.filters.platform == platform and request.filters.sample_size == 1
