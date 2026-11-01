"""Instruments, providers, dataset provenance and ingestion jobs."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, uuid_pk
from app.domain.enums import DatasetStatus, JobStatus


class Instrument(TimestampMixin, Base):
    __tablename__ = "instruments"

    id: Mapped[uuid.UUID] = uuid_pk()
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(32), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    is_tradable: Mapped[bool] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class DataProvider(TimestampMixin, Base):
    __tablename__ = "data_providers"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    # Verified capabilities and their documentation sources.
    capabilities: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)


class DataIngestionJob(TimestampMixin, Base):
    __tablename__ = "data_ingestion_jobs"
    __table_args__ = (Index("ix_data_ingestion_jobs_status", "status", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_providers.id", ondelete="RESTRICT"), nullable=False
    )
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    start_date: Mapped[date] = mapped_column(nullable=False)
    end_date: Mapped[date] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JobStatus.PENDING)
    # Completed chunks, so an interrupted download can resume rather than restart.
    progress: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Dataset(TimestampMixin, Base):
    """An immutable, content-addressed version of one candle series."""

    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("instrument_id", "provider_id", "timeframe", "version"),
        UniqueConstraint("instrument_id", "provider_id", "timeframe", "content_hash"),
        Index("ix_datasets_lookup", "instrument_id", "timeframe", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_providers.id", ondelete="RESTRICT"), nullable=False
    )
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DatasetStatus.BUILDING)
    start_date: Mapped[date | None] = mapped_column()
    end_date: Mapped[date | None] = mapped_column()
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    manifest: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    quality_report: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    ingestion_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("data_ingestion_jobs.id", ondelete="SET NULL")
    )
