"""AI dataset catalogue. Kept apart from backtest execution by design."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, uuid_pk
from app.domain.enums import JobStatus


class AiDataset(TimestampMixin, Base):
    __tablename__ = "ai_datasets"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class AiDatasetVersion(TimestampMixin, Base):
    __tablename__ = "ai_dataset_versions"
    __table_args__ = (UniqueConstraint("ai_dataset_id", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    ai_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_datasets.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    backtest_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("backtest_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    generation_parameters: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    record_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    label_distribution: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    split_statistics: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    validation_report: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JobStatus.PENDING)
    error: Mapped[str | None] = mapped_column(Text)


class DatasetExport(TimestampMixin, Base):
    __tablename__ = "dataset_exports"
    __table_args__ = (UniqueConstraint("ai_dataset_version_id", "format", "split"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    ai_dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_dataset_versions.id", ondelete="RESTRICT"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    split: Mapped[str] = mapped_column(String(16), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    record_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    exported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
