"""API response models."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ComponentHealth(BaseModel):
    status: Literal["ok", "unavailable"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: ComponentHealth
    redis: ComponentHealth


class InstrumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    symbol: str
    name: str
    exchange: str
    instrument_type: str
    timezone: str
    is_tradable: bool


class OverviewResponse(BaseModel):
    instruments: int
    data_providers: int
    datasets: int
    strategies: int
    strategy_versions: int
    backtests: int
    completed_backtests: int
