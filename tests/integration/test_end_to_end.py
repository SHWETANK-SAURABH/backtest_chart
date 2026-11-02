"""The whole workflow through the API alone, with background tasks run in-process.

Download synthetic candles (a labelled test provider stands in for Dhan), register a strategy
version, run a backtest, read its analytics, generate and download reports, build and re-validate an
AI dataset, and reproduce the backtest.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session

from tests.support.mock_market_data import RandomWalkProvider

pytestmark = pytest.mark.integration


@pytest.fixture
def api(
    client: TestClient, db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    """Tasks run synchronously when queued; the provider is the synthetic one."""
    from app.api.routes import ai_datasets, backtests, market_data, reports
    from app.core.config import get_settings
    from app.workers import backtest, datasets, ingestion, reporting

    settings = get_settings()
    monkeypatch.setattr(settings, "data_root", tmp_path)
    monkeypatch.setattr(settings, "dhan_access_token", SecretStr("test-only"))
    monkeypatch.setattr(
        ingestion, "build_provider", lambda code, s: RandomWalkProvider(chunk_days=40)
    )

    for task, function in (
        (market_data.run_ingestion, ingestion.run_ingestion_job),
        (backtests.run_backtest, backtest.run_backtest_job),
        (reports.generate_report, reporting.generate_report_job),
        (ai_datasets.build_dataset, datasets.build_dataset_job),
    ):
        monkeypatch.setattr(task, "apply_async", lambda args, retry, f=function: f(*args))
    return client


def ok(response, status: int = 200) -> dict | list:
    assert response.status_code == status, response.text
    return response.json()


def test_full_workflow_through_the_api(api: TestClient) -> None:
    for timeframe, start in (("5m", "2025-05-20"), ("1d", "2025-04-01")):
        request = {"provider": "dhan", "timeframe": timeframe, "start_date": start}
        request["end_date"] = "2025-06-27"
        job = ok(api.post("/api/v1/market-data/ingest", json=request), 202)
        assert ok(api.get(f"/api/v1/market-data/jobs/{job['id']}"))["status"] == "completed"
    datasets = ok(api.get("/api/v1/market-data/availability"))["datasets"]
    assert {d["timeframe"] for d in datasets} == {"5m", "1d"}
    assert all(d["status"] == "ready" for d in datasets)

    strategy = ok(
        api.post("/api/v1/strategies", json={"name": "MTZ Reversal (end-to-end test)"}), 201
    )
    version = ok(api.post(f"/api/v1/strategies/{strategy['id']}/versions", json={
        "version": "1.0.0", "pine_source": "// test only", "change_description": "e2e",
    }), 201)  # fmt: skip

    backtest = ok(api.post("/api/v1/backtests", json={
        "strategy_version_id": version["id"], "start_date": "2025-06-02", "end_date": "2025-06-27",
        "execution": {"method": "next_open", "slippage_points": 0.5},
    }), 202)  # fmt: skip
    detail = ok(api.get(f"/api/v1/backtests/{backtest['id']}"))
    assert detail["status"] == "completed", detail["error"]

    base = f"/api/v1/backtests/{backtest['id']}"
    metrics = ok(api.get(f"{base}/metrics"))
    trades = ok(api.get(f"{base}/trades"))
    assert trades["total"] == metrics["total_trades"] == detail["trade_count"]
    assert ok(api.get(f"{base}/decisions", params={"limit": 1}))["total"] == 20 * 75
    assert len(ok(api.get(f"{base}/daily"))) == 20
    assert all(t["execution_assumptions"]["slippage_points"] == 0.5 for t in trades["items"])

    queued = ok(api.post(f"{base}/reports", json={
        "categories": ["performance", "trades"], "formats": ["pdf", "csv"],
    }), 202)  # fmt: skip
    for report in ok(api.get(f"{base}/reports")):
        assert report["status"] == "completed", report["error"]
    download = api.get(f"{base}/reports/{queued[0]['id']}/download")
    assert download.status_code == 200 and download.content

    dataset = ok(api.post("/api/v1/ai-datasets/generate", json={
        "name": "e2e", "backtest_id": backtest["id"],
    }), 202)  # fmt: skip
    built = ok(api.get(f"/api/v1/ai-datasets/{dataset['id']}"))
    assert built["status"] == "completed", built["error"]
    assert built["record_count"] == 20 * 75
    assert ok(api.get(f"/api/v1/ai-datasets/{dataset['id']}/validate"))["passed"]
    assert len(ok(api.get(f"/api/v1/ai-datasets/{dataset['id']}/exports"))) == 9

    rerun = ok(api.post(f"{base}/rerun"), 202)
    assert rerun["input_hash"] == backtest["input_hash"]
    check = ok(api.get(f"{base}/reproducibility"))
    assert check["completed_runs"] == 2
    assert check["identical"] is True
    assert {r["id"] for r in check["runs"]} == {backtest["id"], rerun["id"]}


def test_reproducibility_is_unknown_until_a_second_run(
    api: TestClient, db: Session, setup: dict
) -> None:
    from app.backtesting.service import BacktestService
    from tests.support.backtests import make_job

    job = make_job(db, setup)
    BacktestService(db, setup["store"]).run(job.id)
    check = ok(api.get(f"/api/v1/backtests/{job.id}/reproducibility"))
    assert check["completed_runs"] == 1
    assert check["identical"] is None
