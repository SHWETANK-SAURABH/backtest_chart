"""Builds a versioned AI dataset from a completed backtest's stored results.

Layer 1, raw market data, stays in the immutable candle datasets and is referenced by content hash.
Layer 2, structured strategy data, is the backtest's stored decisions, context and trades.
Layer 3, the AI-ready dataset, is built here and never reads the backtest engine directly.
"""

import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    AiDataset,
    AiDatasetVersion,
    BacktestJob,
    Dataset,
    DatasetExport,
    MarketContext,
    StrategyDecision,
    StrategyVersion,
    Trade,
)
from app.datasets import export_manager
from app.datasets.data_cleaner import clean
from app.datasets.data_labeler import decision_labels, outcome_labels, trades_by_signal_time
from app.datasets.dataset_validator import validate
from app.datasets.dataset_version_manager import content_hash, existing_decision_ids
from app.datasets.feature_builder import build_features
from app.datasets.schema import SPLITS
from app.domain.candle import EXCHANGE_TZ
from app.domain.enums import JobStatus

log = structlog.get_logger()


class DatasetParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    train_ratio: float = Field(0.7, gt=0, lt=1)
    validation_ratio: float = Field(0.15, gt=0, lt=1)
    forward_horizons: tuple[int, ...] = Field((1, 3, 6), min_length=1)
    drop_without_levels: bool = True

    @model_validator(mode="after")
    def leave_room_for_test(self) -> "DatasetParameters":
        if self.train_ratio + self.validation_ratio >= 1:
            raise ValueError("train_ratio + validation_ratio must leave room for a test split")
        if any(h < 1 for h in self.forward_horizons):
            raise ValueError("forward horizons must be at least one bar")
        return self


class DatasetBuildError(Exception):
    pass


def assign_splits(sessions: list[str], parameters: DatasetParameters) -> dict[str, str]:
    """Whole sessions, in time order: earliest to train, then validation, then test."""
    if len(sessions) < 3:
        raise DatasetBuildError("At least three sessions are needed for three splits")
    train = max(1, int(len(sessions) * parameters.train_ratio))
    validation = max(1, int(len(sessions) * parameters.validation_ratio))
    if train + validation >= len(sessions):
        train = len(sessions) - validation - 1
    names = ["train"] * train + ["validation"] * validation
    names += ["test"] * (len(sessions) - len(names))
    return dict(zip(sorted(sessions), names, strict=True))


def build_records(
    session: Session, job: BacktestJob, parameters: DatasetParameters, dataset_version: str
) -> list[dict[str, Any]]:
    version = session.get_one(StrategyVersion, job.strategy_version_id)
    data_version = {
        "intraday": session.get_one(Dataset, job.intraday_dataset_id).content_hash,
        "daily": session.get_one(Dataset, job.daily_dataset_id).content_hash,
    }
    trades = trades_by_signal_time(
        [
            {
                "entry_ts": t.entry_ts,
                "net_points": t.net_points,
                "exit_reason": t.exit_reason,
                "holding_seconds": t.holding_seconds,
            }
            for t in session.scalars(select(Trade).where(Trade.backtest_job_id == job.id))
        ]
    )

    sessions: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    rows = session.execute(
        select(StrategyDecision, MarketContext)
        .join(MarketContext, MarketContext.decision_id == StrategyDecision.id)
        .where(StrategyDecision.backtest_job_id == job.id)
        .order_by(StrategyDecision.candle_ts)
    )
    for decision, context in rows:
        decision_data = {
            c.key: getattr(decision, c.key) for c in StrategyDecision.__table__.columns
        }
        context_data = {c.key: getattr(context, c.key) for c in MarketContext.__table__.columns}
        day = decision.candle_ts.astimezone(EXCHANGE_TZ).date().isoformat()
        sessions[day].append((decision_data, context_data))

    records = []
    for day, items in sessions.items():
        closes = [d["close"] for d, _ in items]
        position_before = "flat"
        for index, (row, row_context) in enumerate(items):
            records.append(
                {
                    "timestamp": row["candle_ts"].astimezone(EXCHANGE_TZ).isoformat(),
                    "trading_date": day,
                    "instrument": "NIFTY50",
                    "timeframe": job.timeframe,
                    "features": build_features(row, row_context, position_before),
                    "labels": {
                        "decision": decision_labels(row),
                        "outcome": outcome_labels(
                            row,
                            trades.get(row["candle_ts"]),
                            closes,
                            index,
                            parameters.forward_horizons,
                        ),
                    },
                    "strategy_version": version.version,
                    "strategy_code_hash": version.code_hash,
                    "dataset_version": dataset_version,
                    "data_version": data_version,
                    "source": {"backtest_id": str(job.id), "decision_id": row["id"]},
                    "split": None,
                }
            )
            position_before = row["position_state"]
    return records


def _distribution(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    return {
        "action": dict(Counter(r["labels"]["decision"]["action"] for r in records)),
        "setup_outcome": dict(Counter(r["labels"]["outcome"]["setup_outcome"] for r in records)),
        "trade_result": dict(
            Counter(
                str(r["labels"]["outcome"]["trade_result"])
                for r in records
                if r["labels"]["outcome"]["trade_taken"]
            )
        ),
    }


class DatasetBuilder:
    def __init__(
        self,
        session: Session,
        data_root: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session = session
        self._root = Path(data_root)
        self._clock = clock

    def build(self, version_id: uuid.UUID) -> None:
        version = self._session.get_one(AiDatasetVersion, version_id)
        if version.status != JobStatus.PENDING:
            return
        version.status = JobStatus.RUNNING
        self._session.commit()
        try:
            self._build(version)
        except Exception as exc:
            self._session.rollback()
            version.status = JobStatus.FAILED
            version.error = f"{type(exc).__name__}: {exc}"
            self._session.commit()
            log.exception("dataset.failed", version_id=str(version_id))
            raise

    def _build(self, version: AiDatasetVersion) -> None:
        job = self._session.get_one(BacktestJob, version.backtest_job_id)
        if job.status != JobStatus.COMPLETED:
            raise DatasetBuildError(f"Backtest is {job.status}, not completed")
        parameters = DatasetParameters(**version.generation_parameters["parameters"])

        records, cleaning = clean(
            build_records(self._session, job, parameters, version.version),
            parameters.drop_without_levels,
        )
        splits = assign_splits(sorted({r["trading_date"] for r in records}), parameters)
        for record in records:
            record["split"] = splits[record["trading_date"]]
        records.sort(key=lambda r: (SPLITS.index(r["split"]), r["timestamp"]))

        report = validate(records, self._known_decision_ids)
        report["cleaning"] = cleaning.__dict__
        version.validation_report = report
        version.record_count = len(records)
        version.label_distribution = _distribution(records)
        version.content_hash = content_hash(records)
        version.split_statistics = {
            split: {
                "records": len(rows),
                "sessions": len({r["trading_date"] for r in rows}),
                "first_session": min((r["trading_date"] for r in rows), default=None),
                "last_session": max((r["trading_date"] for r in rows), default=None),
                "labels": _distribution(rows),
            }
            for split in SPLITS
            for rows in [[r for r in records if r["split"] == split]]
        }
        if not report["passed"]:
            # Kept with its report so the failure can be inspected; nothing is exported.
            failed = [c["check"] for c in report["checks"] if not c["passed"]]
            version.status = JobStatus.FAILED
            version.error = f"Validation failed: {', '.join(failed)}"
            self._session.commit()
            return

        dataset = self._session.get_one(AiDataset, version.ai_dataset_id)
        metadata = {
            "dataset": dataset.name,
            "dataset_version": version.version,
            "content_hash": version.content_hash,
            "backtest_id": str(job.id),
            "generation_parameters": version.generation_parameters,
            "units": "theoretical NIFTY 50 index points",
        }
        folder = Path("ai_datasets") / str(dataset.id) / version.version
        for split in SPLITS:
            rows = [r for r in records if r["split"] == split]
            for fmt in export_manager.DATASET_FORMATS:
                relative = folder / f"{split}.{fmt.value}"
                sha = export_manager.write(
                    rows, fmt, self._root / relative, {**metadata, "split": split}
                )
                self._session.add(
                    DatasetExport(
                        ai_dataset_version_id=version.id,
                        format=fmt.value,
                        split=split,
                        file_path=relative.as_posix(),
                        file_size_bytes=(self._root / relative).stat().st_size,
                        sha256=sha,
                        record_count=len(rows),
                        exported_at=self._clock(),
                    )
                )
        version.status = JobStatus.COMPLETED
        self._session.commit()

    def _known_decision_ids(self, ids: Any) -> set[int]:
        return existing_decision_ids(self._session, ids)
