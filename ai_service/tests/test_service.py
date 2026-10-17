import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.errors import ServiceError
from app.groq_client import GROQ_URL, GroqClient, output_schema
from app.main import create_app
from app.ranking import calculate_ranking
from app.schemas import AnalyzeRequest


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Las pruebas no pueden acceder a la red real")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)


@pytest.fixture
def body():
    return json.loads((Path(__file__).parents[1] / "examples/analyze_request.json").read_text(encoding="utf-8"))


def interpretation(source="test-video-a"):
    return {
        "summary": "Demostración con metadatos ficticios.",
        "findings": [{"observation": "El título menciona reportes.", "hypothesis": None, "source_video_ids": [source]}],
        "recommendations": [{"title": "Reportes con IA", "suggested_format": "Tutorial", "reason": "Aplicación para equipos.", "source_video_ids": [source]}],
        "limitations": ["Datos ficticios de prueba."],
    }


class FakeProvider:
    def __init__(self, output=None, error=None):
        self.output = json.dumps(interpretation()) if output is None else output
        self.error = error
        self.contexts = []

    async def generate(self, context):
        self.contexts.append(json.loads(context))
        if self.error:
            raise self.error
        return self.output


def test_ranking_ties_zero_missing_and_order(body):
    request = AnalyzeRequest.model_validate(body)
    rank = calculate_ranking(list(reversed(request.videos)))
    assert [(r.video_id, r.position, r.value) for r in rank] == [
        ("test-video-a", 1, 12000), ("test-video-b", 1, 12000), ("test-video-c", 3, 0),
    ]
    for video in request.videos:
        video.views = None
    assert calculate_ranking(request.videos) == []


@pytest.mark.parametrize("field,value", [
    ("views", -1), ("views", True), ("views", "42"), ("likes", 1.5),
    ("published_at", "2026-10-10T14:00:00"),
    ("metrics_collected_at", "2020-01-01T00:00:00Z"),
    ("url", "https://youtube.com.evil.example/video"), ("title", " "),
])
def test_invalid_video(body, field, value):
    body["videos"][0][field] = value
    with pytest.raises(ValidationError):
        AnalyzeRequest.model_validate(body)


@pytest.mark.parametrize("case", ["empty", "duplicate", "too_many", "long", "missing_metric", "extra"])
def test_invalid_request(body, case):
    if case == "empty":
        body["videos"] = []
    elif case == "duplicate":
        body["videos"][1]["id"] = body["videos"][0]["id"]
    elif case == "too_many":
        body["videos"] = body["videos"] * 8
    elif case == "long":
        body["question"] = "x" * 2001
    elif case == "missing_metric":
        del body["videos"][0]["views"]
    else:
        body["unexpected"] = True
    with pytest.raises(ValidationError):
        AnalyzeRequest.model_validate(body)


def test_health_never_calls_provider():
    fake = FakeProvider(error=AssertionError("must not call"))
    with TestClient(create_app(fake)) as client:
        assert client.get("/health").json() == {"status": "ok"}
    assert fake.contexts == []


def test_default_app_without_key_health_and_analyze(body, monkeypatch):
    monkeypatch.setattr("app.main.Settings", lambda: Settings(_env_file=None, groq_api_key=""))
    with TestClient(create_app()) as client:
        assert client.get("/health").json() == {"status": "ok"}
        response = client.post("/analyze", json=body)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_configuration"
        assert client.get("/openapi.json").status_code == 200


def test_endpoint_uses_request_and_sends_computed_ranking(body):
    fake = FakeProvider()
    with TestClient(create_app(fake)) as client:
        response = client.post("/analyze", json=body)
        assert response.status_code == 200
        result = response.json()
        assert result["unranked_video_ids"] == ["test-video-d"]
        assert result["ranking"] == fake.contexts[0]["ranking"]
        body["videos"][2]["views"] = 50000
        assert client.post("/analyze", json=body).json()["ranking"][0]["video_id"] == "test-video-c"
    assert len(fake.contexts) == 2
    assert fake.contexts[0]["videos"][0]["title"] == body["videos"][0]["title"]


def test_no_views_still_reports_limitations(body):
    for video in body["videos"]:
        video["views"] = None
    with TestClient(create_app(FakeProvider())) as client:
        result = client.post("/analyze", json=body).json()
    assert result["ranking"] == []
    assert len(result["unranked_video_ids"]) == 4
    assert any("No hay visualizaciones" in item for item in result["limitations"])


@pytest.mark.parametrize("output,code", [
    ("not json", "invalid_provider_response"),
    ("{}", "invalid_provider_response"),
    (json.dumps(interpretation("invented-id")), "invalid_source_reference"),
    (json.dumps({**interpretation(), "ranking": []}), "invalid_provider_response"),
])
def test_bad_analysis(body, output, code):
    with TestClient(create_app(FakeProvider(output))) as client:
        response = client.post("/analyze", json=body)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == code


def test_invalid_input_and_body_limit_do_not_call_provider(body):
    fake = FakeProvider()
    with TestClient(create_app(fake)) as client:
        body["question"] = "SECRET_MARKER" * 1000
        response = client.post("/analyze", json=body)
        assert response.status_code == 422
        assert "SECRET_MARKER" not in response.text
        assert client.post("/analyze", content=b"x" * (256 * 1024 + 1)).status_code == 413
        assert client.post("/analyze", content="{").status_code == 422
    assert fake.contexts == []


@pytest.mark.parametrize("status,expected,code,attempts", [
    (429, 503, "provider_rate_limited", 1),
    (401, 503, "provider_authentication", 1),
    (403, 503, "provider_authentication", 1),
    (400, 502, "provider_rejected_request", 1),
    (503, 503, "provider_unavailable", 2),
])
def test_provider_http_errors(status, expected, code, attempts):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="PRIVATE_PROVIDER_DETAILS")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            provider = GroqClient(Settings(_env_file=None, groq_api_key="test-only"), http)
            with pytest.raises(ServiceError) as error:
                await provider.generate("{}")
            assert (error.value.status, error.value.code) == (expected, code)
            assert "PRIVATE" not in error.value.message

    asyncio.run(run())
    assert len(calls) == attempts


@pytest.mark.parametrize("failure", ["timeout", "connection", "malformed", "truncated", "null"])
def test_provider_failures(failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private", request=request)
        if failure == "connection":
            raise httpx.ConnectError("private", request=request)
        if failure == "malformed":
            return httpx.Response(200, text="not json")
        return httpx.Response(200, json={"choices": [{
            "finish_reason": "length" if failure == "truncated" else "stop",
            "message": {"content": None if failure == "null" else "{}"},
        }]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(ServiceError) as error:
                await GroqClient(Settings(_env_file=None, groq_api_key="test-only"), http).generate("{}")
            assert error.value.status == {"timeout": 504, "connection": 503}.get(failure, 502)

    asyncio.run(run())


def test_provider_total_deadline():
    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(ServiceError) as error:
                await GroqClient(Settings(_env_file=None, groq_api_key="test-only", groq_timeout_seconds=0.01), http).generate("{}")
            assert error.value.code == "provider_timeout"

    asyncio.run(run())


def test_transient_failure_then_success():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(interpretation())},
        }]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            content = await GroqClient(Settings(_env_file=None, groq_api_key="test-only"), http).generate("{}")
            assert json.loads(content) == interpretation()

    asyncio.run(run())
    assert len(calls) == 2


def test_real_client_contract_through_endpoint(body):
    calls = []

    def handler(request):
        assert str(request.url) == GROQ_URL
        payload = json.loads(request.content)
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert json.loads(payload["messages"][1]["content"])["ranking"][0]["value"] == 12000
        calls.append(payload)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(interpretation())}}]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GroqClient(Settings(_env_file=None, groq_api_key="test-only"), http)
    try:
        with TestClient(create_app(provider)) as client:
            assert client.post("/analyze", json=body).status_code == 200
    finally:
        asyncio.run(http.aclose())
    assert len(calls) == 1


@pytest.mark.parametrize("settings", [
    {"groq_api_key": ""}, {"groq_api_key": "test-only", "groq_model": "unverified-model"},
])
def test_missing_configuration_does_not_call_provider(settings):
    def handler(request):
        raise AssertionError("No network expected")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(ServiceError) as error:
                await GroqClient(Settings(_env_file=None, **settings), http).generate("{}")
            assert error.value.code == "provider_configuration"

    asyncio.run(run())


def test_strict_schema_required_fields():
    schema = output_schema()

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(schema)


@pytest.mark.parametrize("status,code", [(504, "provider_timeout"), (503, "provider_rate_limited")])
def test_endpoint_propagates_provider_errors(body, status, code):
    with TestClient(create_app(FakeProvider(error=ServiceError(status, code, "Error seguro")))) as client:
        response = client.post("/analyze", json=body)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code

