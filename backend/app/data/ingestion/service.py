"""Runs an ingestion job: download, stage, validate and publish a dataset version."""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import polars as pl
import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data.calendar import nse
from app.data.ingestion.chunking import plan_chunks
from app.data.ingestion.normalize import deduplicate, to_frame
from app.data.ingestion.session_filter import SessionFilterResult, keep_session_bars
from app.data.ingestion.validation import validate_candles
from app.data.providers.base import MarketDataProvider, ProviderChunk, ProviderInstrument
from app.data.storage.candle_store import CandleStore, StagingStore, merge_candles
from app.database.models import DataIngestionJob, Dataset, Instrument
from app.domain.candle import EXCHANGE_TZ
from app.domain.enums import DatasetStatus, JobStatus, Timeframe

log = structlog.get_logger()

# A redelivered task finds these and stops. Failed jobs resume only when explicitly requested.
_TERMINAL = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


class NoCandlesError(Exception):
    """A download produced nothing to publish."""


class IngestionService:
    def __init__(
        self,
        session: Session,
        provider: MarketDataProvider,
        store: CandleStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session = session
        self._provider = provider
        self._store = store
        self._clock = clock

    def run(self, job_id: uuid.UUID) -> None:
        job = self._session.get(DataIngestionJob, job_id)
        if job is None:
            raise ValueError(f"Unknown ingestion job: {job_id}")
        if job.status in _TERMINAL:
            log.info("ingestion.skipped", job_id=str(job_id), status=job.status)
            return

        job.status = JobStatus.RUNNING
        job.started_at = job.started_at or self._clock()
        self._session.commit()
        bound = log.bind(job_id=str(job_id), timeframe=job.timeframe)
        bound.info("ingestion.started")

        try:
            finished = self._download_and_publish(job)
        except Exception as exc:
            self._session.rollback()
            job.status = JobStatus.FAILED
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = self._clock()
            self._session.commit()
            bound.exception("ingestion.failed")
            raise
        if finished:
            job.status = JobStatus.COMPLETED
            job.finished_at = self._clock()
            self._session.commit()
            bound.info("ingestion.completed")

    def _download_and_publish(self, job: DataIngestionJob) -> bool:
        timeframe = Timeframe(job.timeframe)
        instrument_row = self._session.get_one(Instrument, job.instrument_id)
        instrument = self._provider.resolve_instrument(instrument_row.symbol)
        staging = StagingStore(self._store.root, self._provider.code, str(job.id))

        chunks = plan_chunks(job.start_date, job.end_date, self._provider.max_chunk_days(timeframe))
        completed = set(job.progress.get("completed_chunks", []))
        job.progress = {
            "completed_chunks": sorted(completed),
            "total_chunks": len(chunks),
            "instrument": {
                "security_id": instrument.security_id,
                "exchange_segment": instrument.exchange_segment,
                "source": instrument.source,
            },
        }
        self._session.commit()

        for start, end in chunks:
            name = f"{start.isoformat()}_{end.isoformat()}"
            if name in completed:
                continue
            self._session.refresh(job)
            if job.status == JobStatus.CANCELLED:
                job.finished_at = self._clock()
                self._session.commit()
                log.info("ingestion.cancelled", job_id=str(job.id))
                return False
            chunk = self._fetch(instrument, timeframe, start, end)
            staging.save_chunk(name, to_frame(chunk.candles), chunk.raw_payload)
            completed.add(name)
            job.progress = {**job.progress, "completed_chunks": sorted(completed)}
            self._session.commit()

        self._publish(job, timeframe, staging)
        staging.clear_staging()
        return True

    def _fetch(
        self, instrument: ProviderInstrument, timeframe: Timeframe, start: date, end: date
    ) -> ProviderChunk:
        if timeframe == Timeframe.D1:
            return self._provider.get_daily_candles(instrument, start, end)
        return self._provider.get_historical_candles(instrument, timeframe, start, end)

    def _publish(self, job: DataIngestionJob, timeframe: Timeframe, staging: StagingStore) -> None:
        downloaded, stats = deduplicate(staging.load_chunks())
        in_range = downloaded.filter(
            pl.col("trading_date").is_between(job.start_date, job.end_date)
        )
        complete, incomplete = self._split_incomplete(in_range, timeframe)
        outside = SessionFilterResult()
        if timeframe != Timeframe.D1:
            complete, outside = keep_session_bars(complete)
        if complete.is_empty():
            raise NoCandlesError(
                f"Provider returned no complete candles for {job.start_date} to {job.end_date}"
            )

        base = self._latest_ready(job, timeframe)
        revised = 0
        merged = complete
        if base is not None:
            merged, revised = merge_candles(self._store.query(base.manifest), complete)

        report = validate_candles(merged, timeframe, stats.conflicting_duplicates)
        report.revised_candles = revised
        report.excluded_incomplete_candles = incomplete
        report.excluded_outside_session_candles = outside.excluded
        report.excluded_outside_session_by_time = outside.by_time
        report.excluded_outside_session_samples = outside.samples
        written = self._store.write_dataset(merged)

        job.progress = {
            **job.progress,
            "downloaded_rows": downloaded.height,
            "exact_duplicates_removed": stats.exact_duplicates,
            "rows_outside_requested_range": downloaded.height - in_range.height,
        }

        existing = self._session.scalar(
            select(Dataset).where(
                Dataset.instrument_id == job.instrument_id,
                Dataset.provider_id == job.provider_id,
                Dataset.timeframe == timeframe.value,
                Dataset.content_hash == written.content_hash,
            )
        )
        if existing is not None:
            job.progress = {**job.progress, "dataset_id": str(existing.id), "unchanged": True}
            return

        version = self._session.scalar(
            select(func.coalesce(func.max(Dataset.version), 0)).where(
                Dataset.instrument_id == job.instrument_id,
                Dataset.provider_id == job.provider_id,
                Dataset.timeframe == timeframe.value,
            )
        )
        dataset = Dataset(
            instrument_id=job.instrument_id,
            provider_id=job.provider_id,
            timeframe=timeframe.value,
            version=(version or 0) + 1,
            content_hash=written.content_hash,
            status=DatasetStatus.INVALID if report.has_critical_issues else DatasetStatus.READY,
            start_date=written.start_date,
            end_date=written.end_date,
            row_count=written.row_count,
            manifest={
                **written.manifest,
                "based_on_dataset_id": str(base.id) if base is not None else None,
            },
            quality_report=report.to_dict(),
            ingestion_job_id=job.id,
        )
        self._session.add(dataset)
        self._session.flush()
        job.progress = {**job.progress, "dataset_id": str(dataset.id)}

    def _split_incomplete(
        self, frame: pl.DataFrame, timeframe: Timeframe
    ) -> tuple[pl.DataFrame, int]:
        """Exclude bars still forming at download time, which would otherwise leak partial data."""
        now = self._clock()
        if timeframe == Timeframe.D1:
            today = now.astimezone(EXCHANGE_TZ).date()
            todays_session = next(iter(nse.sessions(today, today)), None)
            still_open = todays_session is not None and now < todays_session.close
            complete = frame.filter(pl.col("trading_date") < today) if still_open else frame
        else:
            duration = timedelta(minutes=nse.BAR_MINUTES)
            complete = frame.filter(pl.col("timestamp") + duration <= now.astimezone(UTC))
        return complete, frame.height - complete.height

    def _latest_ready(self, job: DataIngestionJob, timeframe: Timeframe) -> Dataset | None:
        return self._session.scalar(
            select(Dataset)
            .where(
                Dataset.instrument_id == job.instrument_id,
                Dataset.provider_id == job.provider_id,
                Dataset.timeframe == timeframe.value,
                Dataset.status == DatasetStatus.READY,
            )
            .order_by(Dataset.version.desc())
            .limit(1)
        )
