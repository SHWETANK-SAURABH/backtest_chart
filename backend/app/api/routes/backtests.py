"""Backtest jobs."""

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from kombu.exceptions import OperationalError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    BacktestCreate,
    BacktestDetailResponse,
    BacktestJobResponse,
    ReproducibilityResponse,
)
from app.backtesting.service import input_hash
from app.database.models import (
    BacktestJob,
    BacktestJobEvent,
    DataProvider,
    Dataset,
    Instrument,
    StrategyVersion,
    Trade,
)
from app.database.session import get_session
from app.domain.candle import NIFTY50
from app.domain.enums import DatasetStatus, JobStatus, Timeframe
from app.workers.backtest import run_backtest

router = APIRouter(prefix="/backtests", tags=["backtests"])
log = structlog.get_logger()
SessionDep = Annotated[Session, Depends(get_session)]


def _dataset(
    session: Session, dataset_id: uuid.UUID | None, provider_id: uuid.UUID, timeframe: Timeframe
) -> Dataset:
    if dataset_id is not None:
        dataset = session.get(Dataset, dataset_id)
        if dataset is None or dataset.timeframe != timeframe.value:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"No {timeframe} dataset {dataset_id}"
            )
    else:
        dataset = session.scalar(
            select(Dataset)
            .where(
                Dataset.provider_id == provider_id,
                Dataset.timeframe == timeframe.value,
                Dataset.status == DatasetStatus.READY,
            )
            .order_by(Dataset.version.desc())
            .limit(1)
        )
        if dataset is None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"No ready {timeframe} dataset yet")
    if dataset.status != DatasetStatus.READY:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The {timeframe} dataset is {dataset.status}. Review its quality report first.",
        )
    return dataset


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_backtest(request: BacktestCreate, session: SessionDep) -> BacktestJobResponse:
    version = session.get(StrategyVersion, request.strategy_version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy version not found")
    provider = session.scalar(select(DataProvider).where(DataProvider.code == request.provider))
    if provider is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown provider")

    intraday = _dataset(session, request.intraday_dataset_id, provider.id, Timeframe.M5)
    daily = _dataset(session, request.daily_dataset_id, provider.id, Timeframe.D1)
    if (
        intraday.start_date is None
        or intraday.end_date is None
        or not (intraday.start_date <= request.start_date and request.end_date <= intraday.end_date)
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The 5-minute dataset covers {intraday.start_date} to {intraday.end_date}",
        )

    job = BacktestJob(
        strategy_version_id=version.id,
        intraday_dataset_id=intraday.id,
        daily_dataset_id=daily.id,
        instrument_id=session.scalars(
            select(Instrument.id).where(Instrument.symbol == NIFTY50)
        ).one(),
        timeframe=Timeframe.M5.value,
        start_date=request.start_date,
        end_date=request.end_date,
        execution_method=request.execution.method.value,
        execution_settings=request.execution.model_dump(mode="json"),
        risk_settings=request.risk.model_dump(mode="json"),
        capital_assumptions=request.capital.model_dump(mode="json"),
        input_hash=input_hash(
            version,
            intraday,
            daily,
            request.start_date,
            request.end_date,
            request.execution,
            request.risk,
        ),
    )
    session.add(job)
    session.commit()
    _enqueue(session, job)
    return BacktestJobResponse.model_validate(job)


def _enqueue(session: Session, job: BacktestJob) -> None:
    try:
        run_backtest.apply_async(args=[str(job.id)], retry=False)
    except OperationalError as exc:
        log.error("backtest.enqueue_failed", job_id=str(job.id), error=type(exc).__name__)
        job.status = JobStatus.FAILED
        job.error = "Could not reach the job queue. Is Redis running?"
        session.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, job.error) from exc


@router.post("/{job_id}/rerun", status_code=status.HTTP_202_ACCEPTED)
def rerun_backtest(job_id: uuid.UUID, session: SessionDep) -> BacktestJobResponse:
    """Queue a new run with exactly the same strategy version, datasets and settings."""
    original = _get_job(session, job_id)
    job = BacktestJob(
        **{
            column: getattr(original, column)
            for column in (
                "strategy_version_id",
                "intraday_dataset_id",
                "daily_dataset_id",
                "instrument_id",
                "timeframe",
                "start_date",
                "end_date",
                "execution_method",
                "execution_settings",
                "risk_settings",
                "capital_assumptions",
                "input_hash",
            )
        }
    )
    session.add(job)
    session.commit()
    _enqueue(session, job)
    return BacktestJobResponse.model_validate(job)


@router.get("/{job_id}/reproducibility")
def reproducibility(job_id: uuid.UUID, session: SessionDep) -> ReproducibilityResponse:
    """Every run with the same inputs, and whether the completed ones produced identical results."""
    job = _get_job(session, job_id)
    runs = list(
        session.scalars(
            select(BacktestJob)
            .where(BacktestJob.input_hash == job.input_hash)
            .order_by(BacktestJob.created_at)
        )
    )
    results = {r.result_hash for r in runs if r.status == JobStatus.COMPLETED}
    completed = sum(1 for r in runs if r.status == JobStatus.COMPLETED)
    return ReproducibilityResponse(
        input_hash=job.input_hash,
        runs=[
            {
                "id": r.id,
                "status": r.status,
                "result_hash": r.result_hash,
                "created_at": r.created_at,
            }
            for r in runs
        ],
        completed_runs=completed,
        identical=None if completed < 2 else len(results) == 1,
    )


@router.get("")
def list_backtests(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[BacktestJobResponse]:
    rows = session.scalars(select(BacktestJob).order_by(BacktestJob.created_at.desc()).limit(limit))
    return [BacktestJobResponse.model_validate(row) for row in rows]


def _get_job(session: Session, job_id: uuid.UUID) -> BacktestJob:
    job = session.get(BacktestJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backtest not found")
    return job


@router.get("/{job_id}")
def get_backtest(job_id: uuid.UUID, session: SessionDep) -> BacktestDetailResponse:
    job = _get_job(session, job_id)
    events = session.scalars(
        select(BacktestJobEvent)
        .where(BacktestJobEvent.backtest_job_id == job.id)
        .order_by(BacktestJobEvent.occurred_at, BacktestJobEvent.id)
    )
    trades = session.scalar(
        select(func.count()).select_from(Trade).where(Trade.backtest_job_id == job.id)
    )
    return BacktestDetailResponse(
        **BacktestJobResponse.model_validate(job).model_dump(),
        trade_count=trades or 0,
        events=[
            {"type": e.event_type, "message": e.message, "details": e.details, "at": e.occurred_at}
            for e in events
        ],
    )


@router.post("/{job_id}/cancel")
def cancel_backtest(job_id: uuid.UUID, session: SessionDep) -> BacktestJobResponse:
    job = _get_job(session, job_id)
    if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot cancel a {job.status} backtest")
    job.status = JobStatus.CANCELLED
    session.commit()
    return BacktestJobResponse.model_validate(job)
