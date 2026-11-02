"""Fixtures shared by integration tests that need datasets and a strategy version."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.data.ingestion.service import IngestionService
from app.data.storage.candle_store import CandleStore
from app.database.models import (
    AiDataset,
    AiDatasetVersion,
    BacktestJob,
    BacktestJobEvent,
    BacktestMetrics,
    DailyPerformance,
    DataIngestionJob,
    DataProvider,
    Dataset,
    DatasetExport,
    EquityCurvePoint,
    GeneratedReport,
    Instrument,
    MarketContext,
    Strategy,
    StrategyDecision,
    StrategyVersion,
    Trade,
)
from app.domain.enums import DatasetStatus
from app.strategy.parameters import IMPLEMENTATION_VERSION, StrategyParameters
from app.strategy.runner import code_hash
from tests.support.backtests import END
from tests.support.mock_market_data import RandomWalkProvider

# Deleted after each test, children first.
CLEANUP_ORDER = (
    DatasetExport, AiDatasetVersion, AiDataset, GeneratedReport, MarketContext, StrategyDecision,
    Trade, EquityCurvePoint, DailyPerformance,
    BacktestMetrics, BacktestJobEvent, BacktestJob, StrategyVersion, Strategy, Dataset,
    DataIngestionJob,
)  # fmt: skip


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session
    with Session(engine) as session:
        for model in CLEANUP_ORDER:
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
