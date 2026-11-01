"""API endpoints, against real PostgreSQL."""

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_instruments_lists_only_nifty50(client: TestClient) -> None:
    response = client.get("/api/v1/instruments")
    assert response.status_code == 200
    assert [row["symbol"] for row in response.json()] == ["NIFTY50"]
    assert response.json()[0]["is_tradable"] is False


def test_overview_counts_come_from_the_database(client: TestClient) -> None:
    body = client.get("/api/v1/overview").json()
    assert body["instruments"] == 1
    assert body["backtests"] == 0


def test_health_reports_redis_outage_as_degraded(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "redis_url", "redis://127.0.0.1:1/0")
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["database"]["status"] == "ok"
    assert response.json()["redis"]["status"] == "unavailable"
    assert response.json()["status"] == "degraded"
