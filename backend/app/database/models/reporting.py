"""Generated report files."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, uuid_pk
from app.domain.enums import JobStatus


class GeneratedReport(TimestampMixin, Base):
    __tablename__ = "generated_reports"
    __table_args__ = (Index("ix_generated_reports_job", "backtest_job_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    backtest_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("backtest_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JobStatus.PENDING)
    file_path: Mapped[str | None] = mapped_column(String(1024))
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    report_metadata: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
