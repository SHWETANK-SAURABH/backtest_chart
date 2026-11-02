"""AI dataset generation tasks. They run on the backtest queue."""

import uuid

from app.core.config import get_settings
from app.database.session import get_session_factory
from app.datasets.dataset_builder import DatasetBuilder
from app.workers.celery_app import celery_app


def build_dataset_job(version_id: str) -> None:
    with get_session_factory()() as session:
        DatasetBuilder(session, get_settings().data_root).build(uuid.UUID(version_id))


@celery_app.task(name="app.workers.datasets.build_dataset")
def build_dataset(version_id: str) -> None:
    build_dataset_job(version_id)
