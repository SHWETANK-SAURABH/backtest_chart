"""Dataset names, version numbers and content hashes."""

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import AiDataset, AiDatasetVersion, StrategyDecision


def get_or_create_dataset(session: Session, name: str, description: str | None) -> AiDataset:
    dataset = session.scalar(select(AiDataset).where(AiDataset.name == name))
    if dataset is None:
        dataset = AiDataset(name=name, description=description)
        session.add(dataset)
        session.flush()
    return dataset


def next_version(session: Session, dataset: AiDataset) -> str:
    """Versions are "1.0", "2.0", ... in creation order."""
    count = session.scalar(
        select(func.count())
        .select_from(AiDatasetVersion)
        .where(AiDatasetVersion.ai_dataset_id == dataset.id)
    )
    return f"{(count or 0) + 1}.0"


def existing_decision_ids(session: Session, ids: Iterable[int]) -> set[int]:
    """Which of these decision ids exist, batched to stay under PostgreSQL's parameter limit."""
    wanted, found = sorted(ids), set()
    for start in range(0, len(wanted), 10_000):
        batch = wanted[start : start + 10_000]
        found |= set(
            session.scalars(select(StrategyDecision.id).where(StrategyDecision.id.in_(batch)))
        )
    return found


def content_hash(records: list[dict[str, Any]]) -> str:
    """Identifies the records independent of when they were generated or which version label they
    carry, so regenerating with the same inputs gives the same hash."""
    digest = hashlib.sha256()
    for record in records:
        stable = {k: v for k, v in record.items() if k != "dataset_version"}
        digest.update(json.dumps(stable, sort_keys=True, default=str).encode())
        digest.update(b"\n")
    return digest.hexdigest()
