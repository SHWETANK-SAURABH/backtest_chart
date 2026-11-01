"""API request and response models."""

import uuid
from datetime import date, datetime
from typing import Any, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.candle import EXCHANGE_TIMEZONE
from app.domain.enums import Timeframe


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


class IngestRequest(BaseModel):
    provider: str
    timeframe: Timeframe
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        today = datetime.now(ZoneInfo(EXCHANGE_TIMEZONE)).date()
        if self.end_date > today:
            raise ValueError("end_date must not be in the future")
        return self


class IngestionJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_id: uuid.UUID
    timeframe: str
    start_date: date
    end_date: date
    status: str
    progress: dict[str, Any]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class DatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_id: uuid.UUID
    timeframe: str
    version: int
    content_hash: str
    status: str
    start_date: date | None
    end_date: date | None
    row_count: int
    quality_report: dict[str, Any]
    created_at: datetime


class AvailabilityResponse(BaseModel):
    datasets: list[DatasetResponse]


class ProviderHealth(BaseModel):
    code: str
    name: str
    configured: bool
    connected: bool | None = None
    detail: str | None = None
    data_subscription_active: bool | None = None


class MarketDataHealthResponse(BaseModel):
    providers: list[ProviderHealth]
    datasets: list[DatasetResponse]
