"""Runs a backtest job from stored, verified datasets and saves every decision and trade."""

import hashlib
import json
import uuid
from collections.abc import Callable, Iterator
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.backtesting.engine import BacktestEngine, BacktestResult, BarRecord
from app.backtesting.settings import CapitalAssumptions, ExecutionSettings, RiskSettings
from app.data.calendar import nse
from app.data.storage.candle_store import CandleStore
from app.database.models import (
    BacktestJob,
    BacktestJobEvent,
    Dataset,
    MarketContext,
    StrategyDecision,
    StrategyVersion,
    Trade,
)
from app.domain.enums import DatasetStatus, JobStatus
from app.portfolio.position import ClosedTrade
from app.strategy.parameters import StrategyParameters
from app.strategy.runner import BarEvaluation, code_hash, iter_evaluations

log = structlog.get_logger()

# Sessions evaluated before the start date so indicators such as the 50-bar RMA are warm.
WARMUP_SESSIONS = 5
MARKET_STRUCTURE = {"implemented": False, "reason": "not defined in the Pine script"}


class BacktestCancelled(Exception):
    pass


class BacktestInputError(Exception):
    """The job's inputs cannot produce a valid, reproducible backtest."""


def input_hash(
    version: StrategyVersion,
    intraday: Dataset,
    daily: Dataset,
    start: date,
    end: date,
    execution: ExecutionSettings,
    risk: RiskSettings,
) -> str:
    payload = {
        "strategy_version_id": str(version.id),
        "code_hash": version.code_hash,
        "parameters": version.parameters,
        "intraday_dataset": intraday.content_hash,
        "daily_dataset": daily.content_hash,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "execution": execution.model_dump(mode="json"),
        "risk": risk.model_dump(mode="json"),
        "warmup_sessions": WARMUP_SESSIONS,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def warmup_start(start: date) -> date:
    earlier = nse.sessions(start - timedelta(days=45), start - timedelta(days=1))
    return earlier[-WARMUP_SESSIONS].trading_date if len(earlier) >= WARMUP_SESSIONS else start


class BacktestService:
    def __init__(
        self,
        session: Session,
        store: CandleStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session = session
        self._store = store
        self._clock = clock

    def run(self, job_id: uuid.UUID) -> None:
        job = self._session.get(BacktestJob, job_id)
        if job is None:
            raise ValueError(f"Unknown backtest job: {job_id}")
        if job.status != JobStatus.PENDING:
            log.info("backtest.skipped", job_id=str(job_id), status=job.status)
            return

        job.status = JobStatus.RUNNING
        job.started_at = self._clock()
        self._event(job, "started", "Backtest started")
        self._session.commit()

        try:
            result = self._simulate(job)
        except BacktestCancelled:
            self._session.rollback()
            job.finished_at = self._clock()
            self._event(job, "cancelled", "Cancelled; no partial results were saved")
            self._session.commit()
            return
        except Exception as exc:
            self._session.rollback()
            job.status = JobStatus.FAILED
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = self._clock()
            self._event(job, "failed", job.error)
            self._session.commit()
            log.exception("backtest.failed", job_id=str(job_id))
            raise

        self._save(job, result)
        job.result_hash = result.result_hash()
        job.status = JobStatus.COMPLETED
        job.finished_at = self._clock()
        self._event(
            job,
            "completed",
            "Backtest completed",
            {"decisions": len(result.records), "trades": len(result.trades)},
        )
        self._session.commit()

    def _simulate(self, job: BacktestJob) -> BacktestResult:
        version = self._session.get_one(StrategyVersion, job.strategy_version_id)
        if version.code_hash != code_hash():
            raise BacktestInputError(
                "The strategy code has changed since this version was registered, so its results "
                "could not be reproduced. Register a new strategy version."
            )
        parameters = StrategyParameters(**version.parameters)

        datasets = {}
        for name, dataset_id in (
            ("intraday", job.intraday_dataset_id),
            ("daily", job.daily_dataset_id),
        ):
            dataset = self._session.get_one(Dataset, dataset_id)
            if dataset.status != DatasetStatus.READY:
                raise BacktestInputError(f"The {name} dataset is {dataset.status}, not ready")
            self._store.verify(dataset.manifest)
            datasets[name] = dataset

        intraday = self._store.query(
            datasets["intraday"].manifest, start=warmup_start(job.start_date), end=job.end_date
        )
        daily = self._store.query(datasets["daily"].manifest, end=job.end_date)
        if intraday.filter(intraday["trading_date"] >= job.start_date).is_empty():
            raise BacktestInputError("The intraday dataset has no candles in the requested range")

        engine = BacktestEngine(
            ExecutionSettings(**job.execution_settings), RiskSettings(**job.risk_settings)
        )
        evaluations = self._watch_for_cancel(job, iter_evaluations(intraday, daily, parameters))
        return engine.run(evaluations, trade_from=job.start_date)

    def _watch_for_cancel(
        self, job: BacktestJob, evaluations: Iterator[BarEvaluation]
    ) -> Iterator[BarEvaluation]:
        current = None
        for evaluation in evaluations:
            if evaluation.decision.trading_date != current:
                current = evaluation.decision.trading_date
                self._session.refresh(job, ["status"])
                if job.status == JobStatus.CANCELLED:
                    raise BacktestCancelled
            yield evaluation

    def _save(self, job: BacktestJob, result: BacktestResult) -> None:
        if not result.records:
            return
        decision_ids = self._session.scalars(
            insert(StrategyDecision).returning(StrategyDecision.id, sort_by_parameter_order=True),
            [_decision_row(job.id, record) for record in result.records],
        ).all()
        self._session.execute(
            insert(MarketContext),
            [
                _context_row(decision_id, record.decision.context)
                for decision_id, record in zip(decision_ids, result.records, strict=True)
            ],
        )
        if result.trades:
            self._session.execute(
                insert(Trade),
                [_trade_row(job.id, trade, result.assumptions) for trade in result.trades],
            )

    def _event(
        self, job: BacktestJob, kind: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        self._session.add(
            BacktestJobEvent(
                backtest_job_id=job.id,
                event_type=kind,
                message=message,
                details=details or {},
                occurred_at=self._clock(),
            )
        )


def _decision_row(job_id: uuid.UUID, record: BarRecord) -> dict[str, Any]:
    decision = record.decision
    direction = decision.context.get("trade_direction", {})
    return {
        "backtest_job_id": job_id,
        "candle_ts": decision.timestamp,
        "open": decision.open,
        "high": decision.high,
        "low": decision.low,
        "close": decision.close,
        "long_permission": direction.get("allow_long"),
        "short_permission": direction.get("allow_short"),
        "reversal_state": {
            "signals": decision.context.get("reversal_signals", []),
            "entry_signal": asdict(decision.signal) if decision.signal else None,
        },
        "trade_engine_state": {
            "trade_direction": direction,
            "execution_notes": record.execution_notes,
        },
        "action": decision.action.value,
        "reason_codes": decision.reason_codes,
        "explanation": decision.explanation,
        "trade_opened": record.trade_opened,
        "position_closed": record.position_closed,
        "position_state": record.position_state,
    }


def _context_row(decision_id: int, context: dict[str, Any]) -> dict[str, Any]:
    adr = context.get("adr", {})
    return {
        "decision_id": decision_id,
        "cpr": {"daily": context.get("cpr_daily"), "weekly": context.get("cpr_weekly")},
        "camarilla": context.get("camarilla_daily") or {},
        "adr": adr,
        "adr_usage_percent": adr.get("usage_percent"),
        "ema20": context.get("ema_slow"),
        "ema_direction": context.get("ema_slow_direction"),
        "market_structure": MARKET_STRUCTURE,
        # Regime labels are defined with the analytics in Phase 5.
        "market_regime": None,
    }


def _trade_row(
    job_id: uuid.UUID, trade: ClosedTrade, assumptions: dict[str, Any]
) -> dict[str, Any]:
    return {
        "backtest_job_id": job_id,
        "trade_number": trade.number,
        "trading_date": trade.trading_date,
        "side": trade.side.value,
        "entry_ts": trade.entry_time,
        "exit_ts": trade.exit_time,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "stop_loss": trade.stop_loss,
        "target": trade.target,
        "exit_reason": trade.exit_reason,
        "holding_seconds": trade.holding_seconds,
        "gross_points": trade.gross_points,
        "cost_points": trade.cost_points,
        "net_points": trade.net_points,
        "market_regime": None,
        "indicators_at_entry": trade.entry_context,
        "indicators_at_exit": trade.exit_context,
        "decision_reason": trade.entry_reasons,
        "execution_assumptions": {**assumptions, "notes": trade.notes},
    }


__all__ = ["BacktestInputError", "BacktestService", "CapitalAssumptions", "input_hash"]
