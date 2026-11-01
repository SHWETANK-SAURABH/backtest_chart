"""Celery application. Queues are separate so each worker type can scale independently."""

from celery import Celery

from app.core.config import get_settings

INGESTION_QUEUE = "ingestion"
BACKTEST_QUEUE = "backtest"

settings = get_settings()

# No result backend: job state and results live in PostgreSQL.
celery_app = Celery("nifty_backtester", broker=settings.redis_url)
celery_app.conf.update(
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    timezone="UTC",
    broker_transport_options={"socket_connect_timeout": 2},
    broker_connection_retry_on_startup=True,
    task_default_queue=BACKTEST_QUEUE,
    task_routes={"app.workers.ingestion.*": {"queue": INGESTION_QUEUE}},
    include=["app.workers.ingestion"],
)
