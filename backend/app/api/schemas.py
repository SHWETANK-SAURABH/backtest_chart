"""API request and response models."""

import uuid
from datetime import date, datetime
from typing import Any, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtesting.settings import CapitalAssumptions, ExecutionSettings, RiskSettings
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


class StrategyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None


class StrategyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


class StrategyVersionCreate(BaseModel):
    version: str = Field(pattern=r"^[0-9A-Za-z][0-9A-Za-z.\-]{0,31}$")
    pine_source: str | None = None
    pine_source_reference: str | None = Field(None, max_length=512)
    parameters: dict[str, Any] = Field(default_factory=dict)
    change_description: str | None = None

    @model_validator(mode="after")
    def require_source(self) -> Self:
        if not self.pine_source and not self.pine_source_reference:
            raise ValueError("Provide pine_source or pine_source_reference")
        return self


class StrategyVersionResponse(BaseModel):
    """The Pine source itself is not returned; its hash identifies it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_id: uuid.UUID
    version: str
    pine_source_reference: str | None
    pine_source_sha256: str | None = None
    python_implementation_version: str
    code_hash: str
    parameters: dict[str, Any]
    indicator_settings: dict[str, Any]
    execution_settings: dict[str, Any]
    change_description: str | None
    created_at: datetime


class StrategyDetailResponse(StrategyResponse):
    versions: list[StrategyVersionResponse]


class BacktestCreate(BaseModel):
    strategy_version_id: uuid.UUID
    start_date: date
    end_date: date
    provider: str = "dhan"
    intraday_dataset_id: uuid.UUID | None = None
    daily_dataset_id: uuid.UUID | None = None
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    capital: CapitalAssumptions = Field(default_factory=CapitalAssumptions)

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class BacktestJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_version_id: uuid.UUID
    intraday_dataset_id: uuid.UUID
    daily_dataset_id: uuid.UUID
    timeframe: str
    start_date: date
    end_date: date
    execution_method: str
    execution_settings: dict[str, Any]
    risk_settings: dict[str, Any]
    capital_assumptions: dict[str, Any]
    input_hash: str
    result_hash: str | None
    status: str
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class BacktestDetailResponse(BacktestJobResponse):
    trade_count: int
    events: list[dict[str, Any]]
