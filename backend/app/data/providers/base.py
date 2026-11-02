"""The interface every market data provider implements."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.domain.candle import Candle
from app.domain.enums import Timeframe


class ProviderError(Exception):
    """A provider call failed."""


class ProviderAuthError(ProviderError):
    """Credentials are missing, invalid or expired."""


class ProviderSubscriptionError(ProviderError):
    """The account lacks the subscription this data requires."""


class ProviderRateLimitError(ProviderError):
    """Rate limited, and retries were exhausted."""


class ProviderUnavailableError(ProviderError):
    """Network or server failure, and retries were exhausted."""


class ProviderResponseError(ProviderError):
    """The response did not have the documented shape."""


class InstrumentNotFoundError(ProviderError):
    """The provider's instrument list has no unambiguous match."""


@dataclass(frozen=True)
class ProviderInstrument:
    symbol: str
    provider: str
    security_id: str
    exchange_segment: str
    instrument_type: str
    source: str


@dataclass(frozen=True)
class AvailableHistory:
    """What the provider documents. None means the provider does not state a date."""

    timeframe: Timeframe
    earliest_date: date | None
    notes: str


@dataclass(frozen=True)
class ConnectionStatus:
    connected: bool
    detail: str
    data_subscription_active: bool | None = None
    token_valid_until: str | None = None


@dataclass(frozen=True)
class ProviderChunk:
    """Normalised candles alongside the provider's original payload, kept for provenance."""

    candles: list[Candle]
    raw_payload: dict[str, Any] = field(default_factory=dict)
    requested_at: datetime | None = None


class MarketDataProvider(ABC):
    code: str

    @abstractmethod
    def max_chunk_days(self, timeframe: Timeframe) -> int:
        """Most calendar days one request may span."""

    @abstractmethod
    def resolve_instrument(self, symbol: str) -> ProviderInstrument: ...

    @abstractmethod
    def get_historical_candles(
        self, instrument: ProviderInstrument, timeframe: Timeframe, start: date, end: date
    ) -> ProviderChunk:
        """Intraday candles for an inclusive range of exchange-local dates."""

    @abstractmethod
    def get_daily_candles(
        self, instrument: ProviderInstrument, start: date, end: date
    ) -> ProviderChunk:
        """Daily candles for an inclusive range of exchange-local dates."""

    @abstractmethod
    def get_available_history(
        self, instrument: ProviderInstrument, timeframe: Timeframe
    ) -> AvailableHistory: ...

    @abstractmethod
    def validate_connection(self) -> ConnectionStatus: ...
