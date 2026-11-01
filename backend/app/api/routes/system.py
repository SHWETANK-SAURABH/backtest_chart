"""Health and overview endpoints."""

from typing import Annotated, Any

import redis
import structlog
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.schemas import ComponentHealth, HealthResponse, OverviewResponse
from app.core.config import get_settings
from app.database import models
from app.database.session import get_session
from app.domain.enums import JobStatus

router = APIRouter(tags=["system"])
log = structlog.get_logger()
SessionDep = Annotated[Session, Depends(get_session)]


def _check_database(session: Session) -> ComponentHealth:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        log.warning("health.database_unavailable", error=type(exc).__name__)
        return ComponentHealth(status="unavailable", detail="Database connection failed")
    return ComponentHealth(status="ok")


def _check_redis() -> ComponentHealth:
    try:
        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1)
        client.ping()
    except redis.RedisError as exc:
        log.warning("health.redis_unavailable", error=type(exc).__name__)
        return ComponentHealth(status="unavailable", detail="Redis connection failed")
    return ComponentHealth(status="ok")


@router.get("/health")
def health(session: SessionDep, response: Response) -> HealthResponse:
    database = _check_database(session)
    redis_health = _check_redis()
    healthy = database.status == "ok" and redis_health.status == "ok"
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded", database=database, redis=redis_health
    )


@router.get("/overview")
def overview(session: SessionDep) -> OverviewResponse:
    def count(model: Any) -> int:
        return session.scalar(select(func.count()).select_from(model)) or 0

    completed = session.scalar(
        select(func.count())
        .select_from(models.BacktestJob)
        .where(models.BacktestJob.status == JobStatus.COMPLETED)
    )
    return OverviewResponse(
        instruments=count(models.Instrument),
        data_providers=count(models.DataProvider),
        datasets=count(models.Dataset),
        strategies=count(models.Strategy),
        strategy_versions=count(models.StrategyVersion),
        backtests=count(models.BacktestJob),
        completed_backtests=completed or 0,
    )
