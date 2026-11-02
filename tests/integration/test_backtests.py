"""Full backtests on real PostgreSQL and Parquet, using clearly labelled synthetic candles."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.backtesting.service import BacktestInputError, BacktestService, input_hash
from app.backtesting.settings import ExecutionSettings, RiskSettings
from app.data.ingestion.service import IngestionService
from app.data.storage.candle_store import CandleStore
from app.database.models import (
    BacktestJob,
    BacktestJobEvent,
    DataIngestionJob,
    DataProvider,
    Dataset,
    Instrument,
    MarketContext,
    Strategy,
    StrategyDecision,
    StrategyVersion,
    Trade,
)
from app.domain.enums import DatasetStatus, JobStatus
from app.strategy.parameters import IMPLEMENTATION_VERSION, StrategyParameters
from app.strategy.runner import code_hash
from tests.support.mock_market_data import RandomWalkProvider

pytestmark = pytest.mark.integration

START = date(2025, 6, 2)
END = date(2025, 6, 27)


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session
    with Session(engine) as session:
        for model in (
            MarketContext, StrategyDecision, Trade, BacktestJobEvent, BacktestJob,
            StrategyVersion, Strategy, Dataset, DataIngestionJob,
        ):  # fmt: skip
            session.execute(delete(model))
        session.commit()


@pytest.fixture
def setup(db: Session, tmp_path: Path) -> dict:
    """Ingest synthetic 5-minute and daily datasets, and register a strategy version."""
    instrument_id = db.scalars(select(Instrument.id)).one()
    provider_id = db.scalars(select(DataProvider.id).where(DataProvider.code == "dhan")).one()
    store = CandleStore(tmp_path)
    datasets = {}
    for timeframe, start in (("5m", date(2025, 5, 20)), ("1d", date(2025, 4, 1))):
        job = DataIngestionJob(
            instrument_id=instrument_id,
            provider_id=provider_id,
            timeframe=timeframe,
            start_date=start,
            end_date=END,
        )
        db.add(job)
        db.commit()
        IngestionService(db, RandomWalkProvider(chunk_days=40), store).run(job.id)
        datasets[timeframe] = db.scalars(
            select(Dataset).where(Dataset.timeframe == timeframe)
        ).one()
        assert datasets[timeframe].status == DatasetStatus.READY

    strategy = Strategy(name="MTZ Reversal test")
    db.add(strategy)
    db.flush()
    version = StrategyVersion(
        strategy_id=strategy.id,
        version="1.0.0",
        pine_source="// test only",
        python_implementation_version=IMPLEMENTATION_VERSION,
        code_hash=code_hash(),
        parameters=StrategyParameters().model_dump(mode="json"),
    )
    db.add(version)
    db.commit()
    return {"store": store, "version": version, "instrument_id": instrument_id, **datasets}


def make_job(db: Session, setup: dict, execution: ExecutionSettings | None = None) -> BacktestJob:
    execution = execution or ExecutionSettings()
    risk = RiskSettings()
    job = BacktestJob(
        strategy_version_id=setup["version"].id,
        intraday_dataset_id=setup["5m"].id,
        daily_dataset_id=setup["1d"].id,
        instrument_id=setup["instrument_id"],
        timeframe="5m",
        start_date=START,
        end_date=END,
        execution_method=execution.method.value,
        execution_settings=execution.model_dump(mode="json"),
        risk_settings=risk.model_dump(mode="json"),
        input_hash=input_hash(
            setup["version"], setup["5m"], setup["1d"], START, END, execution, risk
        ),
    )
    db.add(job)
    db.commit()
    return job


def count(db: Session, model: type, job: BacktestJob) -> int:
    return (
        db.scalar(select(func.count()).select_from(model).where(model.backtest_job_id == job.id))
        or 0
    )


def test_backtest_records_every_candle_and_its_trades(db: Session, setup: dict) -> None:
    job = make_job(db, setup)
    BacktestService(db, setup["store"]).run(job.id)

    assert job.status == JobStatus.COMPLETED, job.error
    sessions = 20  # trading sessions from 2025-06-02 to 2025-06-27
    assert count(db, StrategyDecision, job) == sessions * 75
    assert db.scalar(select(func.count()).select_from(MarketContext)) == sessions * 75
    trades = db.scalars(
        select(Trade).where(Trade.backtest_job_id == job.id).order_by(Trade.trade_number)
    ).all()
    assert trades, "the synthetic data should produce at least one trade"
    for trade in trades:
        assert trade.entry_ts.date() == trade.exit_ts.date()  # never overnight
        assert trade.entry_ts < trade.exit_ts
        assert trade.trading_date >= START
        assert trade.execution_assumptions["units"].endswith("not rupees")
        assert trade.cost_points == 0
    opened = db.scalar(
        select(func.count())
        .select_from(StrategyDecision)
        .where(StrategyDecision.backtest_job_id == job.id, StrategyDecision.trade_opened)
    )
    assert opened == len(trades)
    assert job.result_hash is not None
    events = [
        e.event_type
        for e in db.scalars(
            select(BacktestJobEvent).where(BacktestJobEvent.backtest_job_id == job.id)
        )
    ]
    assert events == ["started", "completed"]


def test_same_inputs_reproduce_identical_results(db: Session, setup: dict) -> None:
    first, second = make_job(db, setup), make_job(db, setup)
    BacktestService(db, setup["store"]).run(first.id)
    BacktestService(db, setup["store"]).run(second.id)
    assert first.input_hash == second.input_hash
    assert first.result_hash == second.result_hash


def test_execution_method_changes_the_inputs_and_is_recorded(db: Session, setup: dict) -> None:
    from app.domain.enums import ExecutionMethod

    idealised = make_job(db, setup, ExecutionSettings(method=ExecutionMethod.SIGNAL_CLOSE))
    BacktestService(db, setup["store"]).run(idealised.id)
    assert idealised.input_hash != make_job(db, setup).input_hash
    trade = db.scalars(select(Trade).where(Trade.backtest_job_id == idealised.id)).first()
    assert trade is not None
    assert trade.execution_assumptions["signal_close_is_idealised"] is True


def test_completed_backtest_locks_its_strategy_version(db: Session, setup: dict) -> None:
    job = make_job(db, setup)
    BacktestService(db, setup["store"]).run(job.id)
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(
            update(StrategyVersion)
            .where(StrategyVersion.id == setup["version"].id)
            .values(parameters={})
        )
    db.rollback()


def test_changed_strategy_code_is_refused(db: Session, setup: dict) -> None:
    db.execute(update(StrategyVersion).values(code_hash="0" * 64))
    db.commit()
    job = make_job(db, setup)
    with pytest.raises(BacktestInputError, match="changed"):
        BacktestService(db, setup["store"]).run(job.id)
    assert job.status == JobStatus.FAILED
    assert count(db, StrategyDecision, job) == 0


def test_invalid_dataset_is_refused(db: Session, setup: dict) -> None:
    db.execute(
        update(Dataset).where(Dataset.id == setup["1d"].id).values(status=DatasetStatus.INVALID)
    )
    db.commit()
    job = make_job(db, setup)
    with pytest.raises(BacktestInputError, match="invalid"):
        BacktestService(db, setup["store"]).run(job.id)


def test_tampered_dataset_file_is_refused(db: Session, setup: dict) -> None:
    path = setup["store"].root / setup["5m"].manifest["files"][0]["path"]
    path.write_bytes(path.read_bytes() + b"x")
    job = make_job(db, setup)
    with pytest.raises(Exception, match="changed"):
        BacktestService(db, setup["store"]).run(job.id)
    assert job.status == JobStatus.FAILED


def test_cancelled_backtest_saves_nothing(db: Session, setup: dict, engine: Engine) -> None:
    job = make_job(db, setup)

    class CancellingService(BacktestService):
        def _watch_for_cancel(self, job, evaluations):
            with Session(engine) as other:
                other.execute(
                    update(BacktestJob)
                    .where(BacktestJob.id == job.id)
                    .values(status=JobStatus.CANCELLED)
                )
                other.commit()
            return super()._watch_for_cancel(job, evaluations)

    CancellingService(db, setup["store"]).run(job.id)
    db.refresh(job)
    assert job.status == JobStatus.CANCELLED
    assert count(db, StrategyDecision, job) == 0
    assert count(db, Trade, job) == 0


def test_only_pending_jobs_run(db: Session, setup: dict) -> None:
    job = make_job(db, setup)
    BacktestService(db, setup["store"]).run(job.id)
    BacktestService(db, setup["store"]).run(job.id)
    assert count(db, StrategyDecision, job) == 20 * 75


def test_saved_metrics_agree_with_saved_trades(db: Session, setup: dict) -> None:
    from app.database.models import BacktestMetrics, DailyPerformance, EquityCurvePoint

    job = make_job(db, setup)
    BacktestService(db, setup["store"]).run(job.id)
    trades = db.scalars(select(Trade).where(Trade.backtest_job_id == job.id)).all()
    metrics = db.get_one(BacktestMetrics, job.id)

    assert metrics.total_trades == len(trades)
    assert metrics.net_points == pytest.approx(sum(t.net_points for t in trades))
    assert metrics.winning_trades == sum(1 for t in trades if t.net_points > 0)
    assert metrics.sharpe_assumptions["frequency"] == "daily"
    assert metrics.unit_summary["actual_monetary"]["value"] is None
    assert sum(r["trades"] for r in metrics.by_market_condition["weekday"].values()) == len(trades)

    daily = db.scalars(
        select(DailyPerformance).where(DailyPerformance.backtest_job_id == job.id)
    ).all()
    assert len(daily) == 20  # every tested session, with or without trades
    assert sum(r.net_points for r in daily) == pytest.approx(metrics.net_points)

    curve = db.scalars(
        select(EquityCurvePoint)
        .where(EquityCurvePoint.backtest_job_id == job.id)
        .order_by(EquityCurvePoint.ts)
    ).all()
    assert len(curve) == len(trades)
    assert curve[-1].cumulative_points == pytest.approx(metrics.net_points)
    assert max(p.drawdown_points for p in curve) == pytest.approx(metrics.max_drawdown_points)
    assert all(t.market_regime is None or "_" in t.market_regime for t in trades)


def test_analytics_endpoints(client: TestClient, db: Session, setup: dict) -> None:
    job = make_job(db, setup)
    BacktestService(db, setup["store"]).run(job.id)
    base = f"/api/v1/backtests/{job.id}"

    metrics = client.get(f"{base}/metrics").json()
    trades = client.get(f"{base}/trades").json()
    assert trades["total"] == metrics["total_trades"]
    wins = client.get(f"{base}/trades", params={"outcome": "win"}).json()
    assert wins["total"] == metrics["winning_trades"]
    assert all(t["net_points"] > 0 for t in wins["items"])
    assert len(client.get(f"{base}/trades", params={"limit": 1}).json()["items"]) <= 1

    assert len(client.get(f"{base}/equity").json()) == metrics["total_trades"]
    daily = client.get(f"{base}/daily").json()
    assert len(daily) == 20
    monthly = client.get(f"{base}/monthly").json()
    assert [m["trading_date"] for m in monthly] == ["2025-06-01"]
    assert monthly[0]["net_points"] == pytest.approx(metrics["net_points"])

    page = client.get(f"{base}/decisions", params={"limit": 10}).json()
    assert page["total"] == 20 * 75
    assert len(page["items"]) == 10
    assert "cpr" in page["items"][0]["market_context"]
    first_day = client.get(
        f"{base}/decisions",
        params={"start_date": "2025-06-02", "end_date": "2025-06-02", "limit": 100},
    ).json()
    assert first_day["total"] == 75
    holds = client.get(f"{base}/decisions", params={"reason_code": "NO_REVERSAL_SIGNAL"}).json()
    assert 0 < holds["total"] < page["total"]


def test_analytics_require_a_completed_backtest(
    client: TestClient, db: Session, setup: dict
) -> None:
    job = make_job(db, setup)
    assert client.get(f"/api/v1/backtests/{job.id}/metrics").status_code == 409
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/backtests/{missing}/trades").status_code == 404


# API


def request_body(setup: dict, **changes) -> dict:
    return {
        "strategy_version_id": str(setup["version"].id),
        "start_date": START.isoformat(),
        "end_date": END.isoformat(),
        **changes,
    }


def test_create_backtest_uses_latest_ready_datasets_and_queues(
    client: TestClient, setup: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import backtests

    sent: list = []
    monkeypatch.setattr(
        backtests.run_backtest, "apply_async", lambda args, retry: sent.append(args)
    )
    response = client.post(
        "/api/v1/backtests",
        json=request_body(setup, execution={"method": "signal_close", "slippage_points": 0.5}),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["intraday_dataset_id"] == str(setup["5m"].id)
    assert body["daily_dataset_id"] == str(setup["1d"].id)
    assert body["execution_settings"]["slippage_points"] == 0.5
    assert body["capital_assumptions"]["initial_capital"] == 1_000_000
    assert sent == [[body["id"]]]

    detail = client.get(f"/api/v1/backtests/{body['id']}").json()
    assert detail["trade_count"] == 0
    assert body["id"] in [b["id"] for b in client.get("/api/v1/backtests").json()]
    assert client.post(f"/api/v1/backtests/{body['id']}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/v1/backtests/{body['id']}/cancel").status_code == 409


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"start_date": "2025-01-01"}, 422),  # outside the dataset
        ({"start_date": "2025-06-30", "end_date": "2025-06-02"}, 422),
        ({"execution": {"method": "instant"}}, 422),
        ({"execution": {"slippage_points": -1}}, 422),
        ({"risk": {"max_trades_per_day": 0}}, 422),
        ({"strategy_version_id": "00000000-0000-0000-0000-000000000000"}, 404),
    ],
)
def test_create_backtest_validates_input(
    client: TestClient, setup: dict, changes: dict, status: int
) -> None:
    assert (
        client.post("/api/v1/backtests", json=request_body(setup, **changes)).status_code == status
    )


def test_invalid_dataset_cannot_be_selected(client: TestClient, setup: dict, db: Session) -> None:
    db.execute(
        update(Dataset).where(Dataset.id == setup["5m"].id).values(status=DatasetStatus.INVALID)
    )
    db.commit()
    response = client.post(
        "/api/v1/backtests", json=request_body(setup, intraday_dataset_id=str(setup["5m"].id))
    )
    assert response.status_code == 409
    assert "quality report" in response.json()["detail"]
