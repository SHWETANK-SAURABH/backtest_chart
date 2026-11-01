"""Market data availability, ingestion jobs and data health."""

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from kombu.exceptions import OperationalError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.api.schemas import (
    AvailabilityResponse,
    DatasetResponse,
    IngestionJobResponse,
    IngestRequest,
    MarketDataHealthResponse,
    ProviderHealth,
)
from app.core.config import get_settings
from app.data.providers.base import ProviderInstrument
from app.data.providers.registry import SUPPORTED_PROVIDERS, build_provider, is_configured
from app.database.models import DataIngestionJob, DataProvider, Dataset, Instrument
from app.database.session import get_session
from app.domain.candle import NIFTY50
from app.domain.enums import JobStatus, Timeframe
from app.workers.ingestion import run_ingestion

router = APIRouter(prefix="/market-data", tags=["market-data"])
log = structlog.get_logger()
SessionDep = Annotated[Session, Depends(get_session)]


def _latest_datasets(session: Session) -> list[Dataset]:
    latest = (
        select(Dataset)
        .ext(distinct_on(Dataset.provider_id, Dataset.timeframe))
        .order_by(Dataset.provider_id, Dataset.timeframe, Dataset.version.desc())
    )
    return list(session.scalars(latest))


@router.get("/availability")
def availability(session: SessionDep) -> AvailabilityResponse:
    return AvailabilityResponse(
        datasets=[DatasetResponse.model_validate(row) for row in _latest_datasets(session)]
    )


@router.get("/datasets")
def list_datasets(session: SessionDep) -> list[DatasetResponse]:
    rows = session.scalars(select(Dataset).order_by(Dataset.created_at.desc()))
    return [DatasetResponse.model_validate(row) for row in rows]


@router.get("/health")
def market_data_health(
    session: SessionDep,
    check_connection: Annotated[
        bool, Query(description="Also call each configured provider, which is slower.")
    ] = False,
) -> MarketDataHealthResponse:
    settings = get_settings()
    providers = []
    for row in session.scalars(select(DataProvider).order_by(DataProvider.code)):
        configured = is_configured(row.code, settings)
        result = ProviderHealth(code=row.code, name=row.name, configured=configured)
        if check_connection and configured:
            connection = build_provider(row.code, settings).validate_connection()
            result.connected = connection.connected
            result.detail = connection.detail
            result.data_subscription_active = connection.data_subscription_active
        providers.append(result)
    return MarketDataHealthResponse(
        providers=providers,
        datasets=[DatasetResponse.model_validate(row) for row in _latest_datasets(session)],
    )


def _enqueue(session: Session, job: DataIngestionJob) -> None:
    try:
        run_ingestion.apply_async(args=[str(job.id)], retry=False)
    except OperationalError as exc:
        log.error("ingestion.enqueue_failed", job_id=str(job.id), error=type(exc).__name__)
        job.status = JobStatus.FAILED
        job.error = "Could not reach the job queue. Is Redis running?"
        session.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, job.error) from exc


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
def ingest(request: IngestRequest, session: SessionDep) -> IngestionJobResponse:
    settings = get_settings()
    if request.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unsupported provider")
    if not is_configured(request.provider, settings):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Provider {request.provider} has no credentials configured"
        )
    provider_row = session.scalar(select(DataProvider).where(DataProvider.code == request.provider))
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == NIFTY50))
    if provider_row is None or instrument is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Run database migrations first")

    if request.timeframe == Timeframe.M5:
        earliest = (
            build_provider(request.provider, settings)
            .get_available_history(_placeholder_instrument(request.provider), request.timeframe)
            .earliest_date
        )
        if earliest is not None and request.start_date < earliest:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"This provider's 5-minute history starts at {earliest}",
            )

    job = DataIngestionJob(
        instrument_id=instrument.id,
        provider_id=provider_row.id,
        timeframe=request.timeframe.value,
        start_date=request.start_date,
        end_date=request.end_date,
    )
    session.add(job)
    session.commit()
    _enqueue(session, job)
    return IngestionJobResponse.model_validate(job)


def _placeholder_instrument(provider: str) -> ProviderInstrument:
    # Documented history depth does not depend on the identifier, so this avoids a network call.
    return ProviderInstrument(NIFTY50, provider, "", "", "", "")


@router.get("/jobs")
def list_jobs(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[IngestionJobResponse]:
    rows = session.scalars(
        select(DataIngestionJob).order_by(DataIngestionJob.created_at.desc()).limit(limit)
    )
    return [IngestionJobResponse.model_validate(row) for row in rows]


def _get_job(session: Session, job_id: uuid.UUID) -> DataIngestionJob:
    job = session.get(DataIngestionJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ingestion job not found")
    return job


@router.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID, session: SessionDep) -> IngestionJobResponse:
    return IngestionJobResponse.model_validate(_get_job(session, job_id))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: uuid.UUID, session: SessionDep) -> IngestionJobResponse:
    job = _get_job(session, job_id)
    if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot cancel a {job.status} job")
    job.status = JobStatus.CANCELLED
    session.commit()
    return IngestionJobResponse.model_validate(job)


@router.post("/jobs/{job_id}/resume", status_code=status.HTTP_202_ACCEPTED)
def resume_job(job_id: uuid.UUID, session: SessionDep) -> IngestionJobResponse:
    """Continue a failed job from its last completed chunk."""
    job = _get_job(session, job_id)
    if job.status != JobStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot resume a {job.status} job")
    job.status = JobStatus.PENDING
    job.error = None
    job.finished_at = None
    session.commit()
    _enqueue(session, job)
    return IngestionJobResponse.model_validate(job)
