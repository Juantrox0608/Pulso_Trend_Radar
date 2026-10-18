import asyncio
import copy
from datetime import datetime, timezone
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
from radar_backend.collector_contract import collector_parameters, normalize_result
from radar_backend.config import Settings
from radar_backend.main import create_app
from radar_backend.schemas import Filters

SEARCH_ID = "a" * 32


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Real network forbidden")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)


def config(**kwargs):
    return Settings(_env_file=None, collector_poll_interval_seconds=0.001, **kwargs)


@pytest.fixture
def body():
    return json.loads((Path(__file__).parents[1] / "examples/research_request.json").read_text(encoding="utf-8"))


@pytest.fixture
def result():
    return {"estado": "lista", "resumen": {"youtube": {"publicaciones": 4, "metricas": 4, "fallidas": 0}},
        "publicaciones": [{"id": f"yt:test-{i}", "plataforma": "youtube", "titulo": f"FICTICIO {i}",
            "texto": "Fixture, no datos reales", "autor_hash": "not-a-name", "url": f"https://youtu.be/test-{i}",
            "publicada_en": "2026-10-10T12:00:00Z", "capturada_en": "2026-10-11T12:00:00Z", "idioma": "es", "pais": "CO"}
            for i in range(1, 5)],
        "metricas": [{"publicacion_id": f"yt:test-{i}", "capturada_en": f"2026-10-17T06:00:0{i}Z",
            "vistas": views, "likes": 0 if i == 3 else None, "comentarios": None}
            for i, views in enumerate([12000, 12000, 0, None], 1)]}


class FakeCollector:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def collect(self, filters):
        self.calls.append(filters)
        return copy.deepcopy(self.result)


class FakeAI:
    def __init__(self):
        self.requests = []

    async def analyze(self, request):
        self.requests.append(request)
        source = request.videos[0].id
        return AnalyzeResponse(summary="Prueba simulada", findings=[{"observation": "Metadatos de prueba",
            "hypothesis": None, "source_video_ids": [source]}], recommendations=[{"title": "Idea de prueba",
            "suggested_format": "Tutorial", "reason": "Para equipos", "source_video_ids": [source]}],
            limitations=["Sin historial"], ranking=calculate_ranking(request.videos),
            unranked_video_ids=sorted(v.id for v in request.videos if v.views is None))


def test_endpoint_health_and_selection(body, result):
    collector, ai = FakeCollector(result), FakeAI()
    with TestClient(create_app(config(), collector, ai)) as client:
        assert client.get("/health").json()["collector_mode"] == "http"
        assert collector.calls == []
        reply = client.post("/research", json=body)
        assert reply.status_code == 200, reply.text
        data = reply.json()
        assert data["collection"]["simulated"] is False
        assert [r["position"] for r in data["analysis"]["ranking"]] == [1, 1, 3]
        assert len(data["sources"]) == 3
        assert ai.requests[0].audience == body["audience"]
        assert all(v.author is None for v in ai.requests[0].videos)
        assert "crecimiento reciente" in ai.requests[0].question
        assert "FICTICIOS" not in ai.requests[0].question
        body["filters"]["sample_size"] = 1
        assert len(client.post("/research", json=body).json()["sources"]) == 1


def test_per_video_capture_null_zero_and_inputs_unchanged(result):
    before = copy.deepcopy(result)
    videos, _, report = normalize_result(result)
    assert result == before
    assert videos[2].views == 0 and videos[3].views is None
    assert videos[2].likes == 0 and videos[0].likes is None
    assert videos[0].metrics_collected_at.isoformat() == "2026-10-17T06:00:01+00:00"
    assert videos[1].metrics_collected_at != videos[0].metrics_collected_at
    assert len(report["statistics_captured_at_by_id"]) == 4


def test_unmatched_duplicate_invalid_metrics(result):
    result["publicaciones"].append(copy.deepcopy(result["publicaciones"][0]))
    result["publicaciones"].append({"id": "yt:orphan", "plataforma": "youtube"})
    result["metricas"].append({"publicacion_id": "yt:extra", "vistas": 0})
    result["metricas"][1]["vistas"] = True
    videos, _, report = normalize_result(result)
    assert [v.id for v in videos] == ["yt:test-3", "yt:test-4"]
    assert report["duplicate_metadata_ids"] == ["yt:test-1"]
    assert report["metadata_without_statistics"] == ["yt:orphan"]
    assert report["statistics_without_metadata"] == ["yt:extra"]
    assert report["invalid_records"][0]["id"] == "yt:test-2"


def test_duplicate_metrics_not_chosen_arbitrarily(result):
    result["metricas"].append(copy.deepcopy(result["metricas"][0]))
    videos, _, report = normalize_result(result)
    assert "yt:test-1" not in [v.id for v in videos]
    assert report["duplicate_metric_ids"] == ["yt:test-1"]


@pytest.mark.parametrize("value", [-1, "100", 1.5, True])
def test_invalid_metrics_excluded(result, value):
    result["metricas"][0]["vistas"] = value
    videos, _, report = normalize_result(result)
    assert "yt:test-1" not in [v.id for v in videos]
    assert report["invalid_records"]


def test_missing_metric_and_invalid_capture(result):
    del result["metricas"][0]["likes"]
    result["metricas"][1]["capturada_en"] = "2026-10-17T06:00:00"
    videos, _, report = normalize_result(result)
    assert videos[0].likes is None
    assert report["missing_metric_fields"] == [{"id": "yt:test-1", "fields": ["likes"]}]
    assert "yt:test-2" not in [v.id for v in videos]


def test_parameters_mapping():
    now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    f = Filters(query="inteligencia artificial", country="MX", published_after="2026-10-15T12:00:00Z", language="en", sample_size=1)
    assert collector_parameters(f, config(), now) == {"tema": "inteligencia artificial", "redes": ["youtube"], "dias": 3, "paises": ["MX"]}
    assert collector_parameters(Filters(query="IA"), config(), now)["dias"] == 7
    assert collector_parameters(Filters(query="IA"), config(), now)["paises"] == ["CO"]


@pytest.mark.parametrize("query", [", ,", "#", "a,b,c,d,e,f"])
def test_invalid_topics_before_network(query):
    with pytest.raises(ServiceError) as error:
        collector_parameters(Filters(query=query), config())
    assert error.value.status == 422


def test_future_start_rejected_before_network():
    with pytest.raises(ServiceError):
        collector_parameters(Filters(query="IA", published_after="2030-01-01T00:00:00Z"), config(), datetime(2026, 10, 17, tzinfo=timezone.utc))


@pytest.mark.parametrize("field,value", [("language", "en"), ("published_after", "2026-10-16T00:00:00Z"),
    ("published_before", "2026-10-01T00:00:00Z")])
def test_local_filters_skip_ai(body, result, field, value):
    body["filters"][field] = value
    ai = FakeAI()
    with TestClient(create_app(config(), FakeCollector(result), ai)) as client:
        assert client.post("/research", json=body).status_code == 422
    assert ai.requests == []


def test_query_not_reinterpreted_as_literal_substring(body, result):
    assert all("inteligencia artificial" not in p["titulo"] for p in result["publicaciones"])
    with TestClient(create_app(config(), FakeCollector(result), FakeAI())) as client:
        assert client.post("/research", json=body).status_code == 200


@pytest.mark.parametrize("case", ["empty", "all_invalid", "bad_structure"])
def test_no_results_never_calls_ai(body, result, case):
    if case == "empty":
        result["publicaciones"], result["metricas"] = [], []
    elif case == "all_null":
        for metric in result["metricas"]:
            metric["vistas"] = None
    elif case == "all_invalid":
        for row in result["publicaciones"]:
            row["publicada_en"] = "invalid"
    else:
        del result["metricas"]
    ai = FakeAI()
    with TestClient(create_app(config(), FakeCollector(result), ai)) as client:
        assert client.post("/research", json=body).status_code == (502 if case == "bad_structure" else 422)
    assert not ai.requests


def test_http_start_poll_and_real_ai_app(body, result):
    calls = []
    class FakeGroq:
        async def generate(self, context):
            assert len(json.loads(context)["videos"]) == 3
            return json.dumps({"summary": "Prueba", "findings": [], "recommendations": [], "limitations": []})
    with TestClient(create_ai_app(FakeGroq())) as ai_server:
        def handler(request):
            calls.append((request.method, request.url.path))
            assert "authorization" not in request.headers and "x-token" not in request.headers
            if request.url.path == "/busquedas":
                assert request.method == "POST"
                assert json.loads(request.content) == {"tema": "inteligencia artificial", "redes": ["youtube"], "dias": 7, "paises": ["CO"]}
                return httpx.Response(202, json={"id": SEARCH_ID, "estado": "en_curso"})
            if request.url.path.startswith("/busquedas/"):
                assert request.method == "GET"
                return httpx.Response(200, json={"estado": "en_curso", "resumen": {}} if len(calls) == 2 else result)
            reply = ai_server.post("/analyze", json=json.loads(request.content))
            return httpx.Response(reply.status_code, json=reply.json())
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        settings = config(collector_url="https://collector.example")
        try:
            with TestClient(create_app(settings, CollectorClient(settings, http), AIClient(settings, http))) as client:
                reply = client.post("/research", json=body)
                assert reply.status_code == 200, reply.text
                assert reply.json()["collection"]["preparation"]["search_id"] == SEARCH_ID
        finally:
            asyncio.run(http.aclose())
    assert [method for method, _ in calls] == ["POST", "GET", "GET", "POST"]


@pytest.mark.parametrize("case,expected,code", [
    ("ambiguous_timeout", 504, "collector_start_uncertain"),
    ("ambiguous_connection", 503, "collector_start_uncertain"),
    ("invalid_json", 502, "collector_start_uncertain"),
    ("missing_id", 502, "collector_start_uncertain"),
    ("wrong_http", 502, "collector_start_uncertain"),
    ("busy", 503, "collector_busy"), ("rate", 503, "collector_rate_limited"),
    ("rejected", 502, "collector_error"),
    ("failed", 502, "collector_search_failed"), ("unknown_state", 502, "collector_invalid_state"),
    ("lost", 502, "collector_search_lost"), ("large", 502, "collector_start_uncertain"),
])
def test_failures_single_post_no_ai(body, case, expected, code):
    calls = []
    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            if case == "ambiguous_timeout":
                raise httpx.ReadTimeout("private", request=request)
            if case == "ambiguous_connection":
                raise httpx.ConnectError("private", request=request)
            if case == "invalid_json":
                return httpx.Response(202, text="not json")
            if case == "missing_id":
                return httpx.Response(202, json={"estado": "en_curso"})
            if case == "wrong_http":
                return httpx.Response(200, json={"id": SEARCH_ID, "estado": "en_curso"})
            if case == "large":
                return httpx.Response(202, content=b"x" * (2 * 1024 * 1024 + 1))
            if case in {"busy", "rate", "rejected"}:
                return httpx.Response({"busy": 409, "rate": 429, "rejected": 422}[case], text="PRIVATE")
            return httpx.Response(202, json={"id": SEARCH_ID, "estado": "en_curso"})
        if case == "lost":
            return httpx.Response(404)
        return httpx.Response(200, json={"estado": "error" if case == "failed" else "unknown"})
    settings, ai = config(collector_url="https://collector.example"), FakeAI()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with TestClient(create_app(settings, CollectorClient(settings, http), ai)) as client:
            reply = client.post("/research", json=body)
        assert reply.status_code == expected, reply.text
        assert reply.json()["error"]["code"] == code
        assert "PRIVATE" not in reply.text
        assert calls.count("POST") == 1 and ai.requests == []
    finally:
        asyncio.run(http.aclose())


def test_poll_deadline_and_real_pauses(body):
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(202 if request.method == "POST" else 200,
            json={"id": SEARCH_ID, "estado": "en_curso"})
    settings = config(collector_search_timeout_seconds=0.02)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with TestClient(create_app(settings, CollectorClient(settings, http), FakeAI())) as client:
            reply = client.post("/research", json=body)
        assert reply.status_code == 504
        assert SEARCH_ID in reply.json()["error"]["message"]
        assert calls.count("POST") == 1
        assert 1 <= calls.count("GET") < 30
    finally:
        asyncio.run(http.aclose())


@pytest.mark.parametrize("field,value", [("sample_size", 0), ("sample_size", 11), ("sample_size", True),
    ("platform", "instagram"), ("country", "co"), ("published_after", "2026-10-01")])
def test_input_validation(body, field, value):
    body["filters"][field] = value
    with TestClient(create_app(config(), FakeCollector({}), FakeAI())) as client:
        assert client.post("/research", json=body).status_code == 422


def test_size_json_and_cors():
    with TestClient(create_app(config(cors_origins=["http://localhost:5173"]), FakeCollector({}), FakeAI())) as client:
        assert client.post("/research", content="{").status_code == 422
        assert client.post("/research", content=b"x" * (256 * 1024 + 1)).status_code == 413
        assert client.options("/research", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}).status_code == 200
        assert client.options("/research", headers={"Origin": "https://other.example", "Access-Control-Request-Method": "POST"}).status_code == 400


@pytest.mark.parametrize("failure", ["references", "ranking", "upstream"])
def test_ai_contract_unchanged(body, result, failure):
    class BadAI(FakeAI):
        async def analyze(self, request):
            if failure == "upstream":
                raise ServiceError(504, "ai_timeout", "Plazo agotado")
            response = await super().analyze(request)
            if failure == "references":
                response.findings[0].source_video_ids = ["yt:invented"]
            else:
                response.ranking = []
            return response
    with TestClient(create_app(config(), FakeCollector(result), BadAI())) as client:
        assert client.post("/research", json=body).status_code == (504 if failure == "upstream" else 502)


def test_total_deadline(body):
    class Slow:
        async def collect(self, filters):
            await asyncio.sleep(1)
    with TestClient(create_app(config(research_timeout_seconds=0.01), Slow(), FakeAI())) as client:
        assert client.post("/research", json=body).json()["error"]["code"] == "research_timeout"


def test_real_example_config_and_no_mock():
    settings = Settings(_env_file=Path(__file__).parents[1] / ".env.example")
    assert settings.collector_mode == "http"
    assert str(settings.collector_url).startswith("https://radar-recoleccion.onrender.com")
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        config(collector_mode="mock")


@pytest.mark.parametrize("upstream_status,upstream_code,expected", [
    (503, "provider_configuration", 503), (503, "provider_authentication", 503),
    (503, "provider_rate_limited", 503), (503, "provider_unavailable", 503),
    (504, "provider_timeout", 504), (502, "provider_rejected_request", 502),
    (502, "invalid_provider_response", 502), (502, "invalid_source_reference", 502),
    (422, "invalid_input", 502), (413, "body_too_large", 502),
])
def test_ai_http_errors_preserve_safe_diagnostics(body, result, upstream_status, upstream_code, expected):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(upstream_status, json={"error": {
            "code": upstream_code, "message": "SECRET_PROVIDER_BODY", "details": [{"input": "PRIVATE_INPUT"}],
        }})
    settings = config()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with TestClient(create_app(settings, FakeCollector(result), AIClient(settings, http))) as client:
            response = client.post("/research", json=body)
        assert response.status_code == expected
        error = response.json()["error"]
        assert error["code"] == "ai_" + upstream_code
        assert error["details"] == [{"service": "ai", "upstream_status": upstream_status, "upstream_code": upstream_code}]
        assert "SECRET_PROVIDER_BODY" not in response.text and "PRIVATE_INPUT" not in response.text
        assert len(calls) == 1
    finally:
        asyncio.run(http.aclose())


@pytest.mark.parametrize("status,payload,expected", [
    (404, b"<html>PRIVATE</html>", "ai_endpoint_not_found"),
    (405, b"{}", "ai_method_not_allowed"),
    (500, b'{"error":{"code":"PRIVATE_CODE","message":"SECRET"}}', "ai_error"),
    (502, b"not-json", "ai_error"),
    (502, b"x" * 17000, "ai_error"),
    (503, b"{}", "ai_unavailable"),
    (504, b"{}", "ai_timeout"),
    (429, b"{}", "ai_rate_limited"),
    (401, b"{}", "ai_authentication"),
    (422, b'{"detail":[{"input":"PRIVATE"}]}', "ai_error"),
    (502, b'{"error":{"code":["invalid_provider_response"]}}', "ai_error"),
])
def test_unknown_ai_errors_do_not_leak_body(body, result, status, payload, expected):
    settings = config()
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, content=payload)))
    try:
        with TestClient(create_app(settings, FakeCollector(result), AIClient(settings, http))) as client:
            response = client.post("/research", json=body)
        error = response.json()["error"]
        assert error["code"] == expected
        assert error["details"] == [{"service": "ai", "upstream_status": status}]
        assert "PRIVATE" not in response.text and "SECRET" not in response.text
    finally:
        asyncio.run(http.aclose())


def test_real_ai_app_failure_is_diagnosable(body, result):
    class FailingProvider:
        async def generate(self, context):
            raise ServiceError(502, "invalid_provider_response", "INTERNAL_DETAILS")
    with TestClient(create_ai_app(FailingProvider())) as ai_server:
        def handler(request):
            response = ai_server.post("/analyze", json=json.loads(request.content))
            return httpx.Response(response.status_code, json=response.json())
        settings = config()
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with TestClient(create_app(settings, FakeCollector(result), AIClient(settings, http))) as client:
                response = client.post("/research", json=body)
            assert response.status_code == 502
            assert response.json()["error"]["code"] == "ai_invalid_provider_response"
            assert "INTERNAL_DETAILS" not in response.text
        finally:
            asyncio.run(http.aclose())


def test_postman_probe_is_valid_and_ranked():
    from app.schemas import AnalyzeRequest
    path = Path(__file__).parents[1] / "examples/ai_probe_request.json"
    request = AnalyzeRequest.model_validate_json(path.read_text(encoding="utf-8"))
    ranking = calculate_ranking(request.videos)
    assert len(ranking) == 1
    assert ranking[0].video_id == "yt:diagnostic-test" and ranking[0].value == 100


def test_health_identifies_ai_target_without_leaking_credentials(result):
    settings = config(ai_analyze_url="https://private-user:private-password@ia-analisis.onrender.com/analyze?token=private-token")
    collector, ai = FakeCollector(result), FakeAI()
    with TestClient(create_app(settings, collector, ai)) as client:
        response = client.get("/health")
    assert response.json()["ai_target"] == {"host": "ia-analisis.onrender.com", "path": "/analyze"}
    assert "private-" not in response.text
    assert not collector.calls and not ai.requests


def test_tiktok_capture_failure_reaches_frontend_without_calling_ai(body):
    body["filters"]["platform"] = "tiktok"
    result = {"estado": "lista", "search_id": SEARCH_ID, "publicaciones": [], "metricas": [],
              "resumen": {"tiktok": {"publicaciones": 0, "metricas": 0, "fallidas": 0,
                  "detalle": {"cuentas": 3, "cuentas_fallidas": 3, "videos": 0, "detenido": True,
                              "aviso": "PRIVATE_PROVIDER_DETAILS", "token": "PRIVATE_TOKEN"}}}}
    ai = FakeAI()
    with TestClient(create_app(config(), FakeCollector(result), ai)) as client:
        response = client.post("/research", json=body)
    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "collector_capture_failed"
    detail = error["details"][0]
    assert detail["search_id"] == SEARCH_ID
    assert detail["capture"]["cuentas_fallidas"] == 3
    assert detail["ai_called"] is False
    assert detail["reason"] == "capture_failed_or_stopped"
    assert "PRIVATE" not in response.text
    assert ai.requests == []


def test_empty_tiktok_is_distinguished_from_capture_failure(body):
    body["filters"]["platform"] = "tiktok"
    result = {"estado": "lista", "publicaciones": [], "metricas": [],
              "resumen": {"tiktok": {"detalle": {"cuentas": 3, "cuentas_fallidas": 0, "videos": 0}}}}
    ai = FakeAI()
    with TestClient(create_app(config(), FakeCollector(result), ai)) as client:
        response = client.post("/research", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["reason"] == "empty_collection"
    assert not ai.requests
