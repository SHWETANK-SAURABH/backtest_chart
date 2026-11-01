"""Ingestion worker tasks."""

import uuid

from app.core.config import get_settings
from app.data.ingestion.service import IngestionService
from app.data.providers.registry import build_provider
from app.data.storage.candle_store import CandleStore
from app.database.models import DataIngestionJob, DataProvider
from app.database.session import get_session_factory
from app.workers.celery_app import celery_app


def run_ingestion_job(job_id: str) -> None:
    settings = get_settings()
    with get_session_factory()() as session:
        job = session.get_one(DataIngestionJob, uuid.UUID(job_id))
        provider_row = session.get_one(DataProvider, job.provider_id)
        provider = build_provider(provider_row.code, settings)
        IngestionService(session, provider, CandleStore(settings.data_root)).run(job.id)


@celery_app.task(name="app.workers.ingestion.run_ingestion")
def run_ingestion(job_id: str) -> None:
    run_ingestion_job(job_id)
