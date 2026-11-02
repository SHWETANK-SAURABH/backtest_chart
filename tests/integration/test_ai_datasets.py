"""AI datasets built from a real backtest on synthetic candles (test data, not market results)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtesting.service import BacktestService
from app.database.models import AiDatasetVersion, DatasetExport, Trade
from app.datasets.dataset_builder import DatasetBuilder, DatasetParameters
from app.datasets.dataset_version_manager import get_or_create_dataset, next_version
from app.datasets.schema import MARKET_CONTEXT_FEATURES, STRATEGY_STATE_FEATURES
from app.domain.enums import JobStatus
from tests.support.backtests import SESSIONS, make_job

pytestmark = pytest.mark.integration


@pytest.fixture
def completed(db: Session, setup: dict):
    job = make_job(db, setup)
    BacktestService(db, setup["store"]).run(job.id)
    return job


def build(db: Session, job, root: Path, name: str = "mtz-test") -> AiDatasetVersion:
    dataset = get_or_create_dataset(db, name, None)
    version = AiDatasetVersion(
        ai_dataset_id=dataset.id,
        version=next_version(db, dataset),
        backtest_job_id=job.id,
        generation_parameters={
            "backtest_id": str(job.id),
            "parameters": DatasetParameters().model_dump(mode="json"),
        },
    )
    db.add(version)
    db.commit()
    DatasetBuilder(db, root).build(version.id)
    return version


def test_dataset_is_built_validated_split_and_exported(db: Session, setup: dict, completed) -> None:
    root = setup["store"].root
    version = build(db, completed, root)
    assert version.status == JobStatus.COMPLETED, version.error
    assert version.validation_report["passed"]
    assert version.record_count == SESSIONS * 75  # 5 warm-up sessions give levels from day one

    stats = version.split_statistics
    assert [stats[s]["sessions"] for s in ("train", "validation", "test")] == [14, 3, 3]
    assert stats["train"]["last_session"] < stats["validation"]["first_session"]
    assert stats["validation"]["last_session"] < stats["test"]["first_session"]

    trades = db.scalar(
        select(func.count()).select_from(Trade).where(Trade.backtest_job_id == completed.id)
    )
    taken = sum(
        n for k, n in version.label_distribution["setup_outcome"].items() if k.startswith("taken")
    )
    assert taken == trades
    assert sum(version.label_distribution["action"].values()) == version.record_count

    exports = db.scalars(
        select(DatasetExport).where(DatasetExport.ai_dataset_version_id == version.id)
    ).all()
    assert len(exports) == 9
    assert sum(e.record_count for e in exports if e.format == "jsonl") == version.record_count


def test_jsonl_records_follow_the_documented_shape(db: Session, setup: dict, completed) -> None:
    root = setup["store"].root
    version = build(db, completed, root)
    export = db.scalars(
        select(DatasetExport).where(
            DatasetExport.ai_dataset_version_id == version.id,
            DatasetExport.split == "train",
            DatasetExport.format == "jsonl",
        )
    ).one()
    first = json.loads((root / export.file_path).read_text(encoding="utf-8").splitlines()[0])
    assert first["instrument"] == "NIFTY50"
    assert first["timeframe"] == "5m"
    assert first["timestamp"].endswith("+05:30")
    assert set(first["features"]["market_context"]) == set(MARKET_CONTEXT_FEATURES)
    assert set(first["features"]["strategy_state"]) == set(STRATEGY_STATE_FEATURES)
    assert first["labels"]["decision"]["action"] in ("BUY", "SELL", "HOLD")
    assert "forward_return_points_6_bars" in first["labels"]["outcome"]
    assert first["dataset_version"] == "1.0"
    assert first["strategy_version"] == "1.0.0"
    assert first["features"]["strategy_state"]["position_before"] == "flat"


def test_same_backtest_and_parameters_reproduce_the_same_content(
    db: Session, setup: dict, completed
) -> None:
    root = setup["store"].root
    first = build(db, completed, root)
    second = build(db, completed, root)
    assert (first.version, second.version) == ("1.0", "2.0")
    assert first.content_hash == second.content_hash


def test_unfinished_backtest_cannot_be_used(db: Session, setup: dict) -> None:
    job = make_job(db, setup)
    with pytest.raises(Exception, match="not completed"):
        build(db, job, setup["store"].root)


# API


@pytest.fixture
def api(client: TestClient, setup: dict, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.api.routes import ai_datasets
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "data_root", setup["store"].root)
    monkeypatch.setattr(ai_datasets.build_dataset, "apply_async", lambda args, retry: None)
    return client


def test_api_generate_inspect_validate_and_download(
    api: TestClient, db: Session, setup: dict, completed
) -> None:
    response = api.post(
        "/api/v1/ai-datasets/generate",
        json={
            "name": "api-test",
            "backtest_id": str(completed.id),
            "parameters": {"forward_horizons": [1, 12]},
        },
    )
    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["status"] == "pending"
    assert queued["generation_parameters"]["parameters"]["forward_horizons"] == [1, 12]

    DatasetBuilder(db, setup["store"].root).build(queued["id"])
    base = f"/api/v1/ai-datasets/{queued['id']}"
    detail = api.get(base).json()
    assert detail["status"] == "completed"
    assert detail["dataset_name"] == "api-test"
    assert queued["id"] in [v["id"] for v in api.get("/api/v1/ai-datasets").json()]

    report = api.get(f"{base}/validate").json()
    assert report["passed"], report
    assert report["content_hash_matches"]

    exports = api.get(f"{base}/exports").json()
    assert {(e["split"], e["format"]) for e in exports} == {
        (s, f) for s in ("train", "validation", "test") for f in ("jsonl", "csv", "parquet")
    }
    jsonl = next(e for e in exports if e["format"] == "jsonl" and e["split"] == "test")
    download = api.get(f"{base}/exports/{jsonl['id']}/download")
    assert download.status_code == 200
    assert len(download.text.splitlines()) == jsonl["record_count"]


def test_api_validate_detects_a_changed_file(
    api: TestClient, db: Session, setup: dict, completed
) -> None:
    version = build(db, completed, setup["store"].root, "tamper-test")
    export = db.scalars(
        select(DatasetExport).where(DatasetExport.ai_dataset_version_id == version.id)
    ).first()
    path = setup["store"].root / export.file_path
    path.write_bytes(path.read_bytes() + b"\n")
    report = api.get(f"/api/v1/ai-datasets/{version.id}/validate").json()
    assert report["passed"] is False
    assert report["files"]


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"name": "x", "backtest_id": "00000000-0000-0000-0000-000000000000"}, 404),
        ({"name": "", "backtest_id": "00000000-0000-0000-0000-000000000000"}, 422),
        ({"name": "x", "backtest_id": "00000000-0000-0000-0000-000000000000",
          "parameters": {"train_ratio": 0.9, "validation_ratio": 0.1}}, 422),
    ],
)  # fmt: skip
def test_api_validates_generation_requests(api: TestClient, body: dict, status: int) -> None:
    assert api.post("/api/v1/ai-datasets/generate", json=body).status_code == status


def test_api_refuses_an_unfinished_backtest(api: TestClient, db: Session, setup: dict) -> None:
    job = make_job(db, setup)
    response = api.post(
        "/api/v1/ai-datasets/generate", json={"name": "x", "backtest_id": str(job.id)}
    )
    assert response.status_code == 409
