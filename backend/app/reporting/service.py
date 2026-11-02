"""Generates report files for completed backtests."""

import hashlib
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy.orm import Session

from app.database.models import BacktestJob, GeneratedReport
from app.domain.enums import ExportFormat, JobStatus, ReportCategory
from app.reporting.content import build
from app.reporting.exporters import WRITERS

log = structlog.get_logger()


class ReportService:
    def __init__(
        self,
        session: Session,
        data_root: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session = session
        self._root = Path(data_root)
        self._clock = clock

    def generate(self, report_id: uuid.UUID) -> None:
        report = self._session.get_one(GeneratedReport, report_id)
        if report.status != JobStatus.PENDING:
            return
        report.status = JobStatus.RUNNING
        self._session.commit()
        try:
            self._write(report)
        except Exception as exc:
            self._session.rollback()
            report.status = JobStatus.FAILED
            report.error = f"{type(exc).__name__}: {exc}"
            self._session.commit()
            log.exception("report.failed", report_id=str(report_id))
            raise

    def _write(self, report: GeneratedReport) -> None:
        job = self._session.get_one(BacktestJob, report.backtest_job_id)
        if job.status != JobStatus.COMPLETED:
            raise ValueError(f"Backtest is {job.status}, not completed")
        generated_at = self._clock()
        content = build(self._session, job, ReportCategory(report.category), generated_at)

        relative = Path("reports") / str(job.id) / f"{report.category}-{report.id}.{report.format}"
        target = self._root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
        WRITERS[ExportFormat(report.format)](content, temporary)
        os.replace(temporary, target)

        data = target.read_bytes()
        report.file_path = relative.as_posix()
        report.file_size_bytes = len(data)
        report.sha256 = hashlib.sha256(data).hexdigest()
        report.report_metadata = content.metadata
        report.generated_at = generated_at
        report.status = JobStatus.COMPLETED
        self._session.commit()
