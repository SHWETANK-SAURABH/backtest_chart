"""Report generation and download for completed backtests."""

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from kombu.exceptions import OperationalError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ReportCreate, ReportResponse
from app.core.config import get_settings
from app.database.models import BacktestJob, GeneratedReport
from app.database.session import get_session
from app.domain.enums import JobStatus
from app.workers.reporting import generate_report

router = APIRouter(prefix="/backtests/{job_id}/reports", tags=["reports"])
log = structlog.get_logger()
SessionDep = Annotated[Session, Depends(get_session)]

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "csv": "text/csv",
    "json": "application/json",
    "parquet": "application/vnd.apache.parquet",
}


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_reports(
    job_id: uuid.UUID, request: ReportCreate, session: SessionDep
) -> list[ReportResponse]:
    """Queue one report per requested category and format."""
    job = session.get(BacktestJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backtest not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Backtest is {job.status}, not completed")

    reports = [
        GeneratedReport(backtest_job_id=job.id, category=category.value, format=fmt.value)
        for category in request.categories
        for fmt in request.formats
    ]
    session.add_all(reports)
    session.commit()
    try:
        for report in reports:
            generate_report.apply_async(args=[str(report.id)], retry=False)
    except OperationalError as exc:
        log.error("report.enqueue_failed", job_id=str(job.id), error=type(exc).__name__)
        for report in reports:
            if report.status == JobStatus.PENDING:
                report.status = JobStatus.FAILED
                report.error = "Could not reach the job queue. Is Redis running?"
        session.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, reports[0].error) from exc
    return [ReportResponse.model_validate(r) for r in reports]


@router.get("")
def list_reports(job_id: uuid.UUID, session: SessionDep) -> list[ReportResponse]:
    rows = session.scalars(
        select(GeneratedReport)
        .where(GeneratedReport.backtest_job_id == job_id)
        .order_by(GeneratedReport.created_at.desc())
    )
    return [ReportResponse.model_validate(r) for r in rows]


@router.get("/{report_id}/download")
def download_report(job_id: uuid.UUID, report_id: uuid.UUID, session: SessionDep) -> FileResponse:
    report = session.get(GeneratedReport, report_id)
    if report is None or report.backtest_job_id != job_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    if report.status != JobStatus.COMPLETED or report.file_path is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Report is {report.status}")
    root = get_settings().data_root.resolve()
    path = (root / report.file_path).resolve()
    if root not in path.parents or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report file is missing")
    return FileResponse(
        path,
        media_type=MEDIA_TYPES[report.format],
        filename=f"{report.category}-{job_id}.{report.format}",
    )
