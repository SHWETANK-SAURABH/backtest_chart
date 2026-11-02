"""Report generation from a real backtest on synthetic candles (test data, not market results)."""

import csv
import hashlib
import io
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtesting.service import BacktestService
from app.database.models import GeneratedReport, Trade
from app.domain.enums import JobStatus
from app.reporting.service import ReportService
from tests.support.backtests import make_job

pytestmark = pytest.mark.integration

CATEGORIES = ["performance", "trades", "decisions", "market_behaviour"]
FORMATS = ["pdf", "csv", "json", "parquet"]
REQUIRED_METADATA = {
    "backtest_id", "strategy_version", "intraday_dataset", "daily_dataset", "generated_at",
    "instrument", "timeframe", "date_range", "execution_settings", "notice",
}  # fmt: skip


@pytest.fixture
def completed(db: Session, setup: dict):
    job = make_job(db, setup)
    BacktestService(db, setup["store"]).run(job.id)
    assert job.status == JobStatus.COMPLETED
    return job


def generate(db: Session, job, root: Path, category: str, fmt: str) -> GeneratedReport:
    report = GeneratedReport(backtest_job_id=job.id, category=category, format=fmt)
    db.add(report)
    db.commit()
    ReportService(db, root).generate(report.id)
    return report


def csv_rows(path: Path) -> tuple[list[str], list[dict]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    comments = [line for line in lines if line.startswith("#")]
    body = [line for line in lines if not line.startswith("#")]
    return comments, list(csv.DictReader(io.StringIO("\n".join(body))))


@pytest.mark.parametrize("category", CATEGORIES)
@pytest.mark.parametrize("fmt", FORMATS)
def test_every_report_is_generated_with_metadata(
    db: Session,
    setup: dict,
    completed,
    category: str,
    fmt: str,
) -> None:
    root = setup["store"].root
    report = generate(db, completed, root, category, fmt)
    assert report.status == JobStatus.COMPLETED, report.error
    path = root / report.file_path
    data = path.read_bytes()
    assert report.sha256 == hashlib.sha256(data).hexdigest()
    assert report.file_size_bytes == len(data)
    assert set(report.report_metadata) >= REQUIRED_METADATA
    assert report.report_metadata["backtest_id"] == str(completed.id)
    assert "not rupee" in report.report_metadata["notice"]

    if fmt == "pdf":
        assert data.startswith(b"%PDF")
    elif fmt == "json":
        document = json.loads(data)
        assert set(document["metadata"]) >= REQUIRED_METADATA
        assert document["sections"]
    elif fmt == "csv":
        comments, _ = csv_rows(path)
        assert any(str(completed.id) in line for line in comments)
        assert any("not rupee" in line for line in comments)
    else:
        file_metadata = pq.read_schema(path).metadata
        assert json.loads(file_metadata[b"report_metadata"])["backtest_id"] == str(completed.id)


def test_trade_and_decision_exports_contain_every_row(db: Session, setup: dict, completed) -> None:
    root = setup["store"].root
    trades = db.scalar(
        select(func.count()).select_from(Trade).where(Trade.backtest_job_id == completed.id)
    )

    _, rows = csv_rows(root / generate(db, completed, root, "trades", "csv").file_path)
    assert len(rows) == trades
    assert {"entry_price", "exit_price", "stop_loss", "target", "exit_reason", "net_points"} <= set(
        rows[0]
    )

    table = pq.read_table(root / generate(db, completed, root, "decisions", "parquet").file_path)
    assert table.num_rows == 20 * 75
    assert {"action", "reason_codes", "explanation", "cpr_tc", "cam_h3", "adr_usage_percent",
            "ema20", "long_permission", "position_after"} <= set(table.column_names)  # fmt: skip


def test_performance_csv_lists_metrics(db: Session, setup: dict, completed) -> None:
    root = setup["store"].root
    _, rows = csv_rows(root / generate(db, completed, root, "performance", "csv").file_path)
    metrics = {row["metric"] for row in rows}
    assert {
        "win_rate",
        "profit_factor",
        "max_drawdown_points",
        "sharpe_ratio",
        "breakeven_trades",
    } <= metrics


def test_market_behaviour_json_explains_its_labels(db: Session, setup: dict, completed) -> None:
    root = setup["store"].root
    document = json.loads(
        (root / generate(db, completed, root, "market_behaviour", "json").file_path).read_text()
    )
    definitions = next(s for s in document["sections"] if s["title"] == "How labels are calculated")
    assert {row["category"] for row in definitions["rows"]} >= {"trend", "volatility", "gap"}


def test_report_for_an_unfinished_backtest_fails(db: Session, setup: dict) -> None:
    job = make_job(db, setup)
    with pytest.raises(ValueError, match="not completed"):
        generate(db, job, setup["store"].root, "trades", "csv")
    report = db.scalars(select(GeneratedReport)).one()
    assert report.status == JobStatus.FAILED


# API


@pytest.fixture
def api(client: TestClient, setup: dict, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.api.routes import reports
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "data_root", setup["store"].root)
    monkeypatch.setattr(reports.generate_report, "apply_async", lambda args, retry: None)
    return client


def test_reports_api_queues_lists_and_downloads(
    api: TestClient, db: Session, setup: dict, completed
) -> None:
    base = f"/api/v1/backtests/{completed.id}/reports"
    response = api.post(base, json={"categories": ["trades", "trades"], "formats": ["csv", "pdf"]})
    assert response.status_code == 202
    queued = response.json()
    assert sorted(r["format"] for r in queued) == ["csv", "pdf"]
    assert all(r["status"] == "pending" for r in queued)

    first = queued[0]["id"]
    assert api.get(f"{base}/{first}/download").status_code == 409
    ReportService(db, setup["store"].root).generate(queued[0]["id"])
    download = api.get(f"{base}/{first}/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith(("text/csv", "application/pdf"))
    listed = {r["id"]: r for r in api.get(base).json()}
    assert listed[first]["status"] == "completed"
    assert hashlib.sha256(download.content).hexdigest() == listed[first]["sha256"]


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"categories": ["trades"], "formats": ["jsonl"]}, 422),
        ({"categories": ["unknown"], "formats": ["csv"]}, 422),
        ({"categories": [], "formats": ["csv"]}, 422),
    ],
)
def test_reports_api_validates(api: TestClient, completed, body: dict, status: int) -> None:
    assert api.post(f"/api/v1/backtests/{completed.id}/reports", json=body).status_code == status


def test_reports_api_requires_a_completed_backtest(
    api: TestClient, db: Session, setup: dict
) -> None:
    job = make_job(db, setup)
    response = api.post(
        f"/api/v1/backtests/{job.id}/reports", json={"categories": ["trades"], "formats": ["csv"]}
    )
    assert response.status_code == 409
    missing = "00000000-0000-0000-0000-000000000000"
    assert api.get(f"/api/v1/backtests/{job.id}/reports/{missing}/download").status_code == 404
