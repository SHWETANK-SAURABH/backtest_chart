"""Builds backtest jobs over the synthetic datasets created by the integration `setup` fixture."""

from datetime import date

from sqlalchemy.orm import Session

from app.backtesting.service import input_hash
from app.backtesting.settings import ExecutionSettings, RiskSettings
from app.database.models import BacktestJob

START = date(2025, 6, 2)
END = date(2025, 6, 27)
SESSIONS = 20  # trading sessions from START to END


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
