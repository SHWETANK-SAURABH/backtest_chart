"""Enumerations shared across modules and persisted as validated strings."""

from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DatasetStatus(StrEnum):
    BUILDING = "building"
    READY = "ready"
    INVALID = "invalid"


class Timeframe(StrEnum):
    M5 = "5m"
    D1 = "1d"


class ExecutionMethod(StrEnum):
    """Signal-close fills are idealized; next-open fills are the robustness comparison."""

    SIGNAL_CLOSE = "signal_close"
    NEXT_OPEN = "next_open"


class Side(StrEnum):
    LONG = "long"
    SHORT = "short"


class DecisionAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class ReportCategory(StrEnum):
    PERFORMANCE = "performance"
    TRADES = "trades"
    DECISIONS = "decisions"
    MARKET_BEHAVIOUR = "market_behaviour"


class ExportFormat(StrEnum):
    PDF = "pdf"
    CSV = "csv"
    JSON = "json"
    JSONL = "jsonl"
    PARQUET = "parquet"
