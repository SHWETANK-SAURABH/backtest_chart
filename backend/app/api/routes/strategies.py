"""Strategies and their immutable versions."""

import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import (
    StrategyCreate,
    StrategyDetailResponse,
    StrategyResponse,
    StrategyVersionCreate,
    StrategyVersionResponse,
)
from app.database.models import Strategy, StrategyVersion
from app.database.session import get_session
from app.strategy.parameters import IMPLEMENTATION_VERSION, StrategyParameters
from app.strategy.runner import code_hash

router = APIRouter(prefix="/strategies", tags=["strategies"])
SessionDep = Annotated[Session, Depends(get_session)]

# Rules the owner confirmed on 2026-11-02, recorded with each version for provenance.
ENTRY_RULES = {
    "zones": "daily and weekly MTZ (CPR band, BC to TC)",
    "entry": "reversal candle (OR, DR, ER, WR) whose preceding candle touches an MTZ",
    "target": "near edge of the next MTZ in the trade direction",
    "stop": "signal candle low (long) or high (short)",
    "trade_direction_panel": "not used to gate entries",
}


def version_response(version: StrategyVersion) -> StrategyVersionResponse:
    response = StrategyVersionResponse.model_validate(version)
    if version.pine_source is not None:
        response.pine_source_sha256 = hashlib.sha256(version.pine_source.encode()).hexdigest()
    return response


def _get_strategy(session: Session, strategy_id: uuid.UUID) -> Strategy:
    strategy = session.get(Strategy, strategy_id)
    if strategy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")
    return strategy


@router.get("")
def list_strategies(session: SessionDep) -> list[StrategyResponse]:
    rows = session.scalars(select(Strategy).order_by(Strategy.name))
    return [StrategyResponse.model_validate(row) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_strategy(request: StrategyCreate, session: SessionDep) -> StrategyResponse:
    strategy = Strategy(name=request.name, description=request.description)
    session.add(strategy)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A strategy with this name exists") from exc
    return StrategyResponse.model_validate(strategy)


@router.get("/{strategy_id}")
def get_strategy(strategy_id: uuid.UUID, session: SessionDep) -> StrategyDetailResponse:
    strategy = _get_strategy(session, strategy_id)
    versions = session.scalars(
        select(StrategyVersion)
        .where(StrategyVersion.strategy_id == strategy.id)
        .order_by(StrategyVersion.created_at)
    )
    return StrategyDetailResponse(
        **StrategyResponse.model_validate(strategy).model_dump(),
        versions=[version_response(version) for version in versions],
    )


@router.post("/{strategy_id}/versions", status_code=status.HTTP_201_CREATED)
def create_version(
    strategy_id: uuid.UUID, request: StrategyVersionCreate, session: SessionDep
) -> StrategyVersionResponse:
    strategy = _get_strategy(session, strategy_id)
    try:
        parameters = StrategyParameters(**request.parameters)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Invalid parameters: {exc.errors()}"
        ) from exc

    version = StrategyVersion(
        strategy_id=strategy.id,
        version=request.version,
        pine_source=request.pine_source,
        pine_source_reference=request.pine_source_reference,
        python_implementation_version=IMPLEMENTATION_VERSION,
        code_hash=code_hash(),
        parameters=parameters.model_dump(mode="json"),
        indicator_settings={
            key: value
            for key, value in parameters.model_dump(mode="json").items()
            if key != "mtz_periods"
        },
        execution_settings={"entry_rules": ENTRY_RULES},
        change_description=request.change_description,
    )
    session.add(version)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This version number exists") from exc
    return version_response(version)
