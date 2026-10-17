"""Pruebas automáticas de los endpoints de la API FastAPI."""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from radar.api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_get_trends_returns_seed_list(client):
    response = client.get("/api/trends")
    assert response.status_code == 200
    trends = response.json()
    assert len(trends) >= 4
    primer_trend = trends[0]
    # Verificar los campos que el frontend de Next.js necesita obligatoriamente
    assert "id" in primer_trend
    assert "title" in primer_trend
    assert "platform" in primer_trend
    assert "views" in primer_trend
    assert "insight" in primer_trend
    assert "angle" in primer_trend
    assert "hook" in primer_trend
    assert "audience" in primer_trend
    assert "format" in primer_trend


def test_get_trends_search_query(client):
    response = client.get("/api/trends?query=agentes")
    assert response.status_code == 200
    trends = response.json()
    assert len(trends) >= 1
    assert any("agente" in t["title"].lower() or "agente" in t["category"].lower() for t in trends)


def test_get_and_patch_opportunity(client):
    # Obtener oportunidades
    resp = client.get("/api/opportunities")
    assert resp.status_code == 200
    ops = resp.json()
    assert len(ops) > 0
    op_id = ops[0]["id"]

    # Cambiar estado a Aprobada
    patch_resp = client.patch(f"/api/opportunities/{op_id}", json={"status": "Aprobada"})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "Aprobada"


def test_post_publicaciones_endpoint(client):
    ahora = datetime.now(timezone.utc).isoformat()
    # En YouTube, el id nativo debe tener exactamente 11 caracteres (ej. dQw4w9WgXcQ)
    payload = [
        {
            "id": "yt:dQw4w9WgXcQ",
            "plataforma": "youtube",
            "titulo": "Agentes IA en FinTech México",
            "texto": "Explicación completa de cómo implementar agentes en banca",
            "hashtags": ["ia", "fintech"],
            "formato": "video_corto",
            "duracion_segundos": 120,
            "idioma": "es",
            "pais": "MX",
            "tipo_autor": "empresa",
            "autor_hash": "0123456789abcdef",
            "publicada_en": ahora,
            "capturada_en": ahora,
            "origen": "api_oficial"
        }
    ]
    resp = client.post("/api/publicaciones", json=payload)
    assert resp.status_code == 201
    datos = resp.json()
    assert (datos["guardadas"] + datos["actualizadas"]) >= 1
