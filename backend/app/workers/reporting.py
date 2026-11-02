"""Report generation tasks. They run on the backtest queue."""

import uuid

from app.core.config import get_settings
from app.database.session import get_session_factory
from app.reporting.service import ReportService
from app.workers.celery_app import celery_app


def generate_report_job(report_id: str) -> None:
    with get_session_factory()() as session:
        ReportService(session, get_settings().data_root).generate(uuid.UUID(report_id))


@celery_app.task(name="app.workers.reporting.generate_report")
def generate_report(report_id: str) -> None:
    generate_report_job(report_id)
