"""Smoke test: app boots and /health returns 200."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "schedule" in body
        assert body["config"]["base_currency"] == "EUR"
