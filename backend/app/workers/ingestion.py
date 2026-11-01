"""Ingestion worker tasks."""

from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.ingestion.ping")
def ping() -> str:
    return "pong"
