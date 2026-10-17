import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.errors import ServiceError
from app.main import create_app as create_ai_app
from app.ranking import calculate_ranking
from app.schemas import AnalyzeResponse
from radar_backend.clients import AIClient, CollectorClient
from radar_backend.config import Settings
from radar_backend.main import create_app


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Real network forbidden")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)


@pytest.fixture
def body():
    return json.loads((Path(__file__).parents[1] / "examples/research_request.json").read_text(encoding="utf-8"))


def config(**kwargs):
    return Settings(_env_file=None, **kwargs)


class FakeAI:
    def __init__(self):
        self.requests = []

    async def analyze(self, request):
        self.requests.append(request)
        source = request.videos[0].id
        return AnalyzeResponse(
            summary="Prueba simulada", findings=[{"observation": "Metadatos de prueba", "hypothesis": None, "source_video_ids": [source]}],
            recommendations=[{"title": "Idea de prueba", "suggested_format": "Tutorial", "reason": "Para equipos", "source_video_ids": [source]}],
            limitations=["Una sola captura, sin historial."],
            ranking=calculate_ranking(request.videos), unranked_video_ids=[],
        )


def test_local_flow_health_and_dynamic_filters(body):
    fake = FakeAI()
    with TestClient(create_app(config(), ai=fake)) as client:
        assert client.get("/health").json()["collector_mode"] == "mock"
        assert not fake.requests
        response = client.post("/research", json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["collection"]["simulated"] is True
        assert [r["position"] for r in result["analysis"]["ranking"]] == [1, 1, 3]
        assert len(result["sources"]) == 3
        assert "FICTICIOS" in fake.requests[0].question
        assert fake.requests[0].audience == body["audience"]
        assert all(v.author is None for v in fake.requests[0].videos)
        body["filters"]["query"] = "reuniones"
        response = client.post("/research", json=body)
        assert response.status_code == 200
        assert response.json()["analysis"]["ranking"][0]["value"] == 0


@pytest.mark.parametrize("field,value", [("query", "nothing matches"), ("language", "en"), ("country", "MX"),
    ("published_after", "2026-10-16T00:00:00Z")])
def test_empty_filter_results_skip_ai(body, field, value):
    fake = FakeAI()
    body["filters"][field] = value
    with TestClient(create_app(config(), ai=fake)) as client:
        response = client.post("/research", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_usable_videos"
    assert not fake.requests


@pytest.mark.parametrize("field,value", [("sample_size", 0), ("sample_size", 11), ("sample_size", True),
    ("platform", "linkedin"), ("published_after", "2026-10-01"), ("country", "co"),
    ("published_before", "2020-01-01T00:00:00Z")])
def test_invalid_filters(body, field, value):
    fake = FakeAI()
    body["filters"][field] = value
    with TestClient(create_app(config(), ai=fake)) as client:
        assert client.post("/research", json=body).status_code == 422
    assert not fake.requests


def test_invalid_input_and_size(body):
    with TestClient(create_app(config(), ai=FakeAI())) as client:
        assert client.post("/research", json={}).status_code == 422
        assert client.post("/research", content="{").status_code == 422
        assert client.post("/research", content=b"x" * (256 * 1024 + 1)).status_code == 413


def test_http_roundtrip_collector_main_ai_service(body):
    """Both HTTP clients plus the actual AI app; only inference is fake."""
    calls = []

    class FakeGroq:
        async def generate(self, context):
            data = json.loads(context)
            return json.dumps({"summary": "Respuesta de prueba", "findings": [], "recommendations": [], "limitations": []})

    async def mock_export():
        async with httpx.AsyncClient() as http:
            from radar_backend.schemas import Filters
            return await CollectorClient(config(), http).collect(Filters(query="IA"))
    export = asyncio.run(mock_export())
    settings = config(collector_mode="http", collector_url="https://collector.example/search", collector_token="test-token")
    with TestClient(create_ai_app(FakeGroq())) as ai_server:
        def handler(request):
            calls.append(str(request.url))
            if request.url.host == "collector.example":
                assert request.headers["authorization"] == "Bearer test-token"
                assert json.loads(request.content)["filters"]["query"] == "IA"
                return httpx.Response(200, json=export)
            assert str(request.url) == "http://127.0.0.1:8001/analyze"
            ai_body = json.loads(request.content)
            assert len(ai_body["videos"]) == 3
            reply = ai_server.post("/analyze", json=ai_body)
            return httpx.Response(reply.status_code, json=reply.json())

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with TestClient(create_app(settings, CollectorClient(settings, http), AIClient(settings, http))) as client:
                reply = client.post("/research", json=body)
                assert reply.status_code == 200, reply.text
                assert reply.json()["collection"]["mode"] == "http"
                assert reply.json()["analysis"]["ranking"][0]["value"] == 12000
        finally:
            asyncio.run(http.aclose())
    assert len(calls) == 2


@pytest.mark.parametrize("status,expected", [(400, 502), (401, 503), (429, 503), (500, 502), (503, 503), (504, 504)])
def test_collector_errors(body, status, expected):
    settings = config(collector_mode="http", collector_url="https://collector.example/search")
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, text="PRIVATE")))
    fake = FakeAI()
    try:
        with TestClient(create_app(settings, CollectorClient(settings, http), fake)) as client:
            reply = client.post("/research", json=body)
        assert reply.status_code == expected
        assert "PRIVATE" not in reply.text
        assert not fake.requests
    finally:
        asyncio.run(http.aclose())


@pytest.mark.parametrize("failure,expected", [("timeout", 504), ("connection", 503), ("json", 502), ("structure", 502), ("large", 502)])
def test_collector_bad_responses(body, failure, expected):
    settings = config(collector_mode="http", collector_url="https://collector.example/search")
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private", request=request)
        if failure == "connection":
            raise httpx.ConnectError("private", request=request)
        return httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1) if failure == "large" else b"{" if failure == "json" else b"{}")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with TestClient(create_app(settings, CollectorClient(settings, http), FakeAI())) as client:
            assert client.post("/research", json=body).status_code == expected
    finally:
        asyncio.run(http.aclose())


def test_http_mode_never_falls_back_to_mock(body):
    fake = FakeAI()
    with TestClient(create_app(config(collector_mode="http"), ai=fake)) as client:
        reply = client.post("/research", json=body)
    assert reply.status_code == 503
    assert reply.json()["error"]["code"] == "collector_configuration"
    assert not fake.requests


@pytest.mark.parametrize("failure", ["references", "ranking", "upstream"])
def test_ai_errors(body, failure):
    class BadAI(FakeAI):
        async def analyze(self, request):
            if failure == "upstream":
                raise ServiceError(504, "ai_timeout", "Plazo agotado")
            result = await super().analyze(request)
            if failure == "references":
                result.findings[0].source_video_ids = ["yt:invented"]
            else:
                result.ranking = []
            return result
    with TestClient(create_app(config(), ai=BadAI())) as client:
        reply = client.post("/research", json=body)
    assert reply.status_code == (504 if failure == "upstream" else 502)


def test_total_deadline(body):
    class Slow:
        async def collect(self, filters):
            await asyncio.sleep(1)
    with TestClient(create_app(config(research_timeout_seconds=0.01), collector=Slow(), ai=FakeAI())) as client:
        reply = client.post("/research", json=body)
    assert reply.status_code == 504
    assert reply.json()["error"]["code"] == "research_timeout"


def test_empty_collector_url_from_example():
    assert Settings(_env_file=Path(__file__).parents[1] / ".env.example").collector_url is None


def test_cors_is_explicit():
    with TestClient(create_app(config(cors_origins=["http://localhost:5173"]), ai=FakeAI())) as client:
        response = client.options("/research", headers={"Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert client.options("/research", headers={"Origin": "https://unconfigured.example",
            "Access-Control-Request-Method": "POST"}).status_code == 400
