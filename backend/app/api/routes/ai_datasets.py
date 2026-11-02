"""AI dataset generation, inspection, validation and export download.

`{id}` is a dataset version id: every version is an immutable set of records and files.
"""

import hashlib
import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from kombu.exceptions import OperationalError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    AiDatasetExportResponse,
    AiDatasetGenerate,
    AiDatasetVersionResponse,
)
from app.core.config import get_settings
from app.database.models import AiDataset, AiDatasetVersion, BacktestJob, DatasetExport
from app.database.session import get_session
from app.datasets import export_manager
from app.datasets.dataset_validator import validate
from app.datasets.dataset_version_manager import (
    content_hash,
    existing_decision_ids,
    get_or_create_dataset,
    next_version,
)
from app.datasets.schema import SPLITS
from app.domain.enums import JobStatus
from app.workers.datasets import build_dataset

router = APIRouter(prefix="/ai-datasets", tags=["ai-datasets"])
log = structlog.get_logger()
SessionDep = Annotated[Session, Depends(get_session)]

MEDIA_TYPES = {
    "jsonl": "application/x-ndjson",
    "csv": "text/csv",
    "parquet": "application/vnd.apache.parquet",
}


def _response(session: Session, version: AiDatasetVersion) -> AiDatasetVersionResponse:
    dataset = session.get_one(AiDataset, version.ai_dataset_id)
    return AiDatasetVersionResponse.model_validate(
        {**{c.key: getattr(version, c.key) for c in AiDatasetVersion.__table__.columns},
         "dataset_name": dataset.name}
    )  # fmt: skip


def _version(session: Session, version_id: uuid.UUID) -> AiDatasetVersion:
    version = session.get(AiDatasetVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset version not found")
    return version


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
def generate(request: AiDatasetGenerate, session: SessionDep) -> AiDatasetVersionResponse:
    job = session.get(BacktestJob, request.backtest_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backtest not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Backtest is {job.status}, not completed")

    dataset = get_or_create_dataset(session, request.name, request.description)
    version = AiDatasetVersion(
        ai_dataset_id=dataset.id,
        version=next_version(session, dataset),
        backtest_job_id=job.id,
        generation_parameters={
            "backtest_id": str(job.id),
            "parameters": request.parameters.model_dump(mode="json"),
        },
    )
    session.add(version)
    session.commit()
    try:
        build_dataset.apply_async(args=[str(version.id)], retry=False)
    except OperationalError as exc:
        log.error("dataset.enqueue_failed", version_id=str(version.id), error=type(exc).__name__)
        version.status = JobStatus.FAILED
        version.error = "Could not reach the job queue. Is Redis running?"
        session.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, version.error) from exc
    return _response(session, version)


@router.get("")
def list_versions(session: SessionDep) -> list[AiDatasetVersionResponse]:
    rows = session.scalars(select(AiDatasetVersion).order_by(AiDatasetVersion.created_at.desc()))
    return [_response(session, row) for row in rows]


@router.get("/{version_id}")
def get_version(version_id: uuid.UUID, session: SessionDep) -> AiDatasetVersionResponse:
    return _response(session, _version(session, version_id))


def _exports(session: Session, version: AiDatasetVersion) -> list[DatasetExport]:
    return list(
        session.scalars(
            select(DatasetExport)
            .where(DatasetExport.ai_dataset_version_id == version.id)
            .order_by(DatasetExport.split, DatasetExport.format)
        )
    )


@router.get("/{version_id}/validate")
def revalidate(version_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    """Re-check the published files: checksums, then every rule on the records read back."""
    version = _version(session, version_id)
    if version.status != JobStatus.COMPLETED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Dataset is {version.status}")
    root = get_settings().data_root
    exports = _exports(session, version)

    file_problems = []
    for export in exports:
        path = root / export.file_path
        if not path.exists():
            file_problems.append(f"missing {export.file_path}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != export.sha256:
            file_problems.append(f"changed {export.file_path}")
    if file_problems:
        return {"passed": False, "files": file_problems, "checks": []}

    parquet = {e.split: e for e in exports if e.format == "parquet"}
    records = [
        r for split in SPLITS for r in export_manager.read_parquet(root / parquet[split].file_path)
    ]

    report = validate(records, lambda ids: existing_decision_ids(session, ids))
    report["files"] = []
    report["content_hash_matches"] = content_hash(records) == version.content_hash
    report["passed"] = report["passed"] and report["content_hash_matches"]
    return report


@router.get("/{version_id}/exports")
def list_exports(version_id: uuid.UUID, session: SessionDep) -> list[AiDatasetExportResponse]:
    version = _version(session, version_id)
    return [AiDatasetExportResponse.model_validate(e) for e in _exports(session, version)]


@router.get("/{version_id}/exports/{export_id}/download")
def download_export(
    version_id: uuid.UUID, export_id: uuid.UUID, session: SessionDep
) -> FileResponse:
    export = session.get(DatasetExport, export_id)
    if export is None or export.ai_dataset_version_id != version_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export not found")
    root = get_settings().data_root.resolve()
    path = (root / export.file_path).resolve()
    if root not in path.parents or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export file is missing")
    return FileResponse(
        path, media_type=MEDIA_TYPES[export.format], filename=f"{export.split}.{export.format}"
    )
