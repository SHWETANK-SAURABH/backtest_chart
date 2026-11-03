"""Builds backtest jobs over the synthetic datasets created by the integration `setup` fixture."""

from datetime import date

from sqlalchemy.orm import Session

from app.backtesting.service import input_hash
from app.backtesting.settings import ExecutionSettings, RiskSettings
from app.database.models import BacktestJob
from app.domain.enums import Timeframe
from app.strategy.parameters import StrategyOptions

START = date(2025, 6, 2)
END = date(2025, 6, 27)
SESSIONS = 20  # trading sessions from START to END


def make_job(
    db: Session,
    setup: dict,
    execution: ExecutionSettings | None = None,
    options: StrategyOptions | None = None,
    timeframe: Timeframe = Timeframe.M5,
) -> BacktestJob:
    execution = execution or ExecutionSettings()
    options = options or StrategyOptions()
    risk = RiskSettings()
    job = BacktestJob(
        strategy_version_id=setup["version"].id,
        intraday_dataset_id=setup["5m"].id,
        daily_dataset_id=setup["1d"].id,
        instrument_id=setup["instrument_id"],
        timeframe=timeframe.value,
        start_date=START,
        end_date=END,
        execution_method=execution.method.value,
        execution_settings=execution.model_dump(mode="json"),
        risk_settings=risk.model_dump(mode="json"),
        strategy_options=options.model_dump(mode="json"),
        input_hash=input_hash(
            setup["version"],
            setup["5m"],
            setup["1d"],
            START,
            END,
            execution,
            risk,
            options,
            timeframe,
        ),
    )
    db.add(job)
    db.commit()
    return job
