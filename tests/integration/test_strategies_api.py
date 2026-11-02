"""Strategy endpoints against real PostgreSQL."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.strategy.parameters import IMPLEMENTATION_VERSION
from app.strategy.runner import code_hash

pytestmark = pytest.mark.integration

PINE = "//@version=6\nindicator('test only')\n"


def create(client: TestClient) -> dict:
    response = client.post("/api/v1/strategies", json={"name": f"test-{uuid.uuid4()}"})
    assert response.status_code == 201
    return response.json()


def test_version_records_implementation_and_hides_source(client: TestClient) -> None:
    strategy = create(client)
    response = client.post(
        f"/api/v1/strategies/{strategy['id']}/versions",
        json={"version": "1.0.0", "pine_source": PINE, "change_description": "first"},
    )
    assert response.status_code == 201
    version = response.json()
    assert version["code_hash"] == code_hash()
    assert version["python_implementation_version"] == IMPLEMENTATION_VERSION
    assert version["parameters"]["adr_length"] == 10
    assert version["parameters"]["mtz_periods"] == ["D", "W"]
    assert version["execution_settings"]["entry_rules"]["stop"].startswith("signal candle")
    assert "pine_source" not in version
    assert len(version["pine_source_sha256"]) == 64

    detail = client.get(f"/api/v1/strategies/{strategy['id']}").json()
    assert [v["version"] for v in detail["versions"]] == ["1.0.0"]
    assert strategy["id"] in [s["id"] for s in client.get("/api/v1/strategies").json()]


def test_duplicate_names_and_versions_conflict(client: TestClient) -> None:
    strategy = create(client)
    assert client.post("/api/v1/strategies", json={"name": strategy["name"]}).status_code == 409
    url = f"/api/v1/strategies/{strategy['id']}/versions"
    assert client.post(url, json={"version": "1", "pine_source": PINE}).status_code == 201
    assert client.post(url, json={"version": "1", "pine_source": PINE}).status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"version": "1"},
        {"version": "bad version", "pine_source": PINE},
        {"version": "1", "pine_source": PINE, "parameters": {"adr_length": 0}},
        {"version": "1", "pine_source": PINE, "parameters": {"unknown": 1}},
    ],
)
def test_invalid_versions_are_rejected(client: TestClient, body: dict) -> None:
    strategy = create(client)
    response = client.post(f"/api/v1/strategies/{strategy['id']}/versions", json=body)
    assert response.status_code == 422


def test_unknown_strategy_is_404(client: TestClient) -> None:
    assert client.get(f"/api/v1/strategies/{uuid.uuid4()}").status_code == 404
