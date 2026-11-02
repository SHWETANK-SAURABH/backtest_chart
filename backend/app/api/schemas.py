"""API request and response models."""

import uuid
from datetime import date, datetime
from typing import Any, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtesting.settings import CapitalAssumptions, ExecutionSettings, RiskSettings
from app.datasets.dataset_builder import DatasetParameters
from app.domain.candle import EXCHANGE_TIMEZONE
from app.domain.enums import ExportFormat, ReportCategory, Timeframe


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


class MetricsResponse(BaseModel):
    """All point values are theoretical NIFTY 50 index points."""

    model_config = ConfigDict(from_attributes=True)

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float | None
    gross_profit_points: float
    gross_loss_points: float
    net_points: float
    profit_factor: float | None
    expectancy_points: float | None
    average_trade_points: float | None
    average_win_points: float | None
    average_loss_points: float | None
    max_drawdown_points: float | None
    average_holding_seconds: float | None
    max_consecutive_wins: int
    max_consecutive_losses: int
    sharpe_ratio: float | None
    sharpe_assumptions: dict[str, Any]
    by_market_condition: dict[str, Any]
    unit_summary: dict[str, Any]


class TradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trade_number: int
    trading_date: date
    side: str
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    stop_loss: float | None
    target: float | None
    exit_reason: str
    holding_seconds: int
    gross_points: float
    cost_points: float
    net_points: float
    market_regime: str | None
    indicators_at_entry: dict[str, Any]
    indicators_at_exit: dict[str, Any]
    decision_reason: list[Any]
    execution_assumptions: dict[str, Any]


class TradePage(BaseModel):
    total: int
    items: list[TradeResponse]


class EquityPointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    cumulative_points: float
    drawdown_points: float


class DailyPerformanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trading_date: date
    trades: int
    wins: int
    losses: int
    net_points: float


class DecisionResponse(BaseModel):
    candle_ts: datetime
    open: float
    high: float
    low: float
    close: float
    action: str
    reason_codes: list[Any]
    explanation: str
    long_permission: bool | None
    short_permission: bool | None
    reversal_state: dict[str, Any]
    trade_engine_state: dict[str, Any]
    trade_opened: bool
    position_closed: bool
    position_state: str
    market_context: dict[str, Any]


class DecisionPage(BaseModel):
    total: int
    items: list[DecisionResponse]


ReportFormat = Literal[ExportFormat.PDF, ExportFormat.CSV, ExportFormat.JSON, ExportFormat.PARQUET]


class ReportCreate(BaseModel):
    categories: list[ReportCategory] = Field(min_length=1)
    formats: list[ReportFormat] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self) -> Self:
        self.categories = list(dict.fromkeys(self.categories))
        self.formats = list(dict.fromkeys(self.formats))
        return self


class AiDatasetGenerate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    backtest_id: uuid.UUID
    parameters: DatasetParameters = Field(default_factory=DatasetParameters)


class AiDatasetVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ai_dataset_id: uuid.UUID
    dataset_name: str
    version: str
    backtest_job_id: uuid.UUID
    generation_parameters: dict[str, Any]
    content_hash: str | None
    record_count: int
    label_distribution: dict[str, Any]
    split_statistics: dict[str, Any]
    validation_report: dict[str, Any]
    status: str
    error: str | None
    created_at: datetime


class AiDatasetExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    format: str
    split: str
    file_size_bytes: int
    sha256: str
    record_count: int
    exported_at: datetime


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    backtest_job_id: uuid.UUID
    category: str
    format: str
    status: str
    file_size_bytes: int | None
    sha256: str | None
    report_metadata: dict[str, Any]
    error: str | None
    created_at: datetime
    generated_at: datetime | None
