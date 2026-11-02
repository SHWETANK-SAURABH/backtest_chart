"""Backtest worker tasks."""

import uuid

from app.backtesting.service import BacktestService
from app.core.config import get_settings
from app.data.storage.candle_store import CandleStore
from app.database.session import get_session_factory
from app.workers.celery_app import celery_app


def run_backtest_job(job_id: str) -> None:
    with get_session_factory()() as session:
        BacktestService(session, CandleStore(get_settings().data_root)).run(uuid.UUID(job_id))


@celery_app.task(name="app.workers.backtest.run_backtest")
def run_backtest(job_id: str) -> None:
    run_backtest_job(job_id)
