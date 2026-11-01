"""Migrations and database constraints, against real PostgreSQL."""

import uuid
from datetime import date

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.database import models
from app.database.base import Base
from tests.conftest import alembic_config

pytestmark = pytest.mark.integration

REQUIRED_TABLES = {
    "instruments",
    "data_providers",
    "datasets",
    "data_ingestion_jobs",
    "strategies",
    "strategy_versions",
    "backtest_jobs",
    "trades",
    "strategy_decisions",
    "market_context",
    "backtest_metrics",
    "equity_curve",
    "daily_performance",
    "generated_reports",
    "ai_datasets",
    "ai_dataset_versions",
    "dataset_exports",
    "backtest_job_events",
}


def test_all_required_tables_exist(engine: Engine) -> None:
    assert set(inspect(engine).get_table_names()) >= REQUIRED_TABLES


def test_migrations_match_models(engine: Engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_migrations_are_reversible(engine: Engine) -> None:
    command.downgrade(alembic_config(), "base")
    assert "instruments" not in inspect(engine).get_table_names()
    command.upgrade(alembic_config(), "head")
    assert set(inspect(engine).get_table_names()) >= REQUIRED_TABLES


def test_nifty50_is_seeded_as_a_non_tradable_index(session: Session) -> None:
    nifty = session.scalar(select(models.Instrument).where(models.Instrument.symbol == "NIFTY50"))
    assert nifty is not None
    assert nifty.exchange == "NSE"
    assert nifty.timezone == "Asia/Kolkata"
    assert nifty.is_tradable is False


def _backtest(session: Session, status: str = "completed") -> models.StrategyVersion:
    instrument = session.scalar(
        select(models.Instrument).where(models.Instrument.symbol == "NIFTY50")
    )
    assert instrument is not None
    provider = models.DataProvider(code=f"t-{uuid.uuid4().hex[:12]}", name="Test only")
    strategy = models.Strategy(name=f"test-{uuid.uuid4()}")
    session.add_all([provider, strategy])
    session.flush()
    version = models.StrategyVersion(
        strategy_id=strategy.id,
        version="1",
        python_implementation_version="test",
        code_hash="a" * 64,
    )
    datasets = [
        models.Dataset(
            instrument_id=instrument.id,
            provider_id=provider.id,
            timeframe=timeframe,
            version=1,
            content_hash=timeframe.ljust(64, "0"),
        )
        for timeframe in ("5m", "1d")
    ]
    session.add_all([version, *datasets])
    session.flush()
    session.add(
        models.BacktestJob(
            strategy_version_id=version.id,
            intraday_dataset_id=datasets[0].id,
            daily_dataset_id=datasets[1].id,
            instrument_id=instrument.id,
            timeframe="5m",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            execution_method="next_open",
            input_hash="b" * 64,
            status=status,
        )
    )
    session.flush()
    return version


def test_strategy_version_is_immutable_after_completed_backtest(session: Session) -> None:
    version = _backtest(session)
    with pytest.raises(DBAPIError, match="immutable"):
        session.execute(
            update(models.StrategyVersion)
            .where(models.StrategyVersion.id == version.id)
            .values(code_hash="c" * 64)
        )


def test_strategy_version_can_change_before_completion(session: Session) -> None:
    version = _backtest(session, status="pending")
    session.execute(
        update(models.StrategyVersion)
        .where(models.StrategyVersion.id == version.id)
        .values(change_description="still editable")
    )


def test_duplicate_candle_decision_is_rejected(session: Session) -> None:
    version = _backtest(session, status="pending")
    job = session.scalar(
        select(models.BacktestJob).where(models.BacktestJob.strategy_version_id == version.id)
    )
    assert job is not None
    insert = text(
        "INSERT INTO strategy_decisions (backtest_job_id, candle_ts, open, high, low, close, "
        "reversal_state, trade_engine_state, action, reason_codes, explanation, trade_opened, "
        "position_closed, position_state) VALUES (:job, '2025-01-01T03:45:00Z', 1, 1, 1, 1, "
        "'{}', '{}', 'HOLD', '[]', 'test', false, false, 'flat')"
    )
    session.execute(insert, {"job": job.id})
    with pytest.raises(IntegrityError):
        session.execute(insert, {"job": job.id})
