"""MOCK MARKET DATA FOR AUTOMATED TESTS ONLY.

Everything here is synthetic and does not represent real NIFTY 50 prices. It must never be used in
a production workflow.
"""

import random
from datetime import UTC, date, datetime, timedelta

from app.data.calendar import nse
from app.data.providers.base import (
    AvailableHistory,
    ConnectionStatus,
    MarketDataProvider,
    ProviderChunk,
    ProviderInstrument,
)
from app.domain.candle import EXCHANGE_TZ, NIFTY50, Candle
from app.domain.enums import Timeframe

MOCK_PROVIDER = "mock"
INGESTED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def mock_candle(
    timestamp: datetime,
    timeframe: Timeframe = Timeframe.M5,
    price: float = 100.0,
    high: float | None = None,
    low: float | None = None,
    volume: int | None = None,
) -> Candle:
    return Candle(
        symbol=NIFTY50,
        timeframe=timeframe,
        timestamp=timestamp,
        open=price,
        high=price + 1 if high is None else high,
        low=price - 1 if low is None else low,
        close=price,
        volume=volume,
        provider=MOCK_PROVIDER,
        ingested_at=INGESTED_AT,
    )


def mock_session_candles(day: date, price: float = 100.0) -> list[Candle]:
    session = nse.sessions(day, day)[0]
    return [mock_candle(bar, price=price) for bar in nse.expected_bar_opens(session)]


def mock_daily_candle(day: date, price: float = 100.0) -> Candle:
    midnight = datetime(day.year, day.month, day.day, tzinfo=EXCHANGE_TZ)
    return mock_candle(midnight, Timeframe.D1, price)


class MockProvider(MarketDataProvider):
    """Serves synthetic candles for every scheduled session, and records its calls."""

    code = "dhan"

    def __init__(self, chunk_days: int = 10, price: float = 100.0) -> None:
        self.chunk_days = chunk_days
        self.price = price
        self.calls: list[tuple[date, date]] = []
        self.fail_on_call: int | None = None
        self.on_call = None
        self.empty = False

    def max_chunk_days(self, timeframe: Timeframe) -> int:
        return self.chunk_days

    def resolve_instrument(self, symbol: str) -> ProviderInstrument:
        return ProviderInstrument(symbol, self.code, "mock-id", "MOCK", "INDEX", "mock")

    def _record(self, start: date, end: date) -> None:
        self.calls.append((start, end))
        if self.on_call is not None:
            self.on_call()
        if self.fail_on_call == len(self.calls):
            raise ConnectionError("mock provider failure")

    def get_historical_candles(
        self, instrument: ProviderInstrument, timeframe: Timeframe, start: date, end: date
    ) -> ProviderChunk:
        self._record(start, end)
        candles: list[Candle] = []
        if not self.empty:
            for session in nse.sessions(start, end):
                candles.extend(mock_session_candles(session.trading_date, self.price))
        return ProviderChunk(candles, {"mock": True})

    def get_daily_candles(
        self, instrument: ProviderInstrument, start: date, end: date
    ) -> ProviderChunk:
        self._record(start, end)
        candles = [mock_daily_candle(s.trading_date, self.price) for s in nse.sessions(start, end)]
        return ProviderChunk(candles, {"mock": True})

    def get_available_history(
        self, instrument: ProviderInstrument, timeframe: Timeframe
    ) -> AvailableHistory:
        return AvailableHistory(timeframe, date(2020, 1, 1) - timedelta(days=1), "mock")

    def validate_connection(self) -> ConnectionStatus:
        return ConnectionStatus(True, "mock")


def random_walk_session(day: date) -> list[Candle]:
    """A seeded random walk for one session. Deterministic per date. Synthetic, not market data."""
    rng = random.Random(day.toordinal())
    session = nse.sessions(day, day)[0]
    price = 22000 + rng.uniform(-300, 300)
    candles = []
    for opened in nse.expected_bar_opens(session):
        close = price + rng.gauss(0, 12)
        high = max(price, close) + abs(rng.gauss(0, 6))
        low = min(price, close) - abs(rng.gauss(0, 6))
        candles.append(
            Candle(
                symbol=NIFTY50,
                timeframe=Timeframe.M5,
                timestamp=opened,
                open=round(price, 2),
                high=round(high, 2),
                low=round(low, 2),
                close=round(close, 2),
                volume=None,
                provider=MOCK_PROVIDER,
                ingested_at=INGESTED_AT,
            )
        )
        price = close
    return candles


class RandomWalkProvider(MockProvider):
    """Synthetic moving prices, with daily candles consistent with the 5-minute candles."""

    def get_historical_candles(
        self, instrument: ProviderInstrument, timeframe: Timeframe, start: date, end: date
    ) -> ProviderChunk:
        self._record(start, end)
        candles = [c for s in nse.sessions(start, end) for c in random_walk_session(s.trading_date)]
        return ProviderChunk(candles, {"mock": True})

    def get_daily_candles(
        self, instrument: ProviderInstrument, start: date, end: date
    ) -> ProviderChunk:
        self._record(start, end)
        candles = []
        for session in nse.sessions(start, end):
            bars = random_walk_session(session.trading_date)
            midnight = datetime.combine(session.trading_date, datetime.min.time(), EXCHANGE_TZ)
            candles.append(
                Candle(
                    symbol=NIFTY50,
                    timeframe=Timeframe.D1,
                    timestamp=midnight,
                    open=bars[0].open,
                    high=max(b.high for b in bars),
                    low=min(b.low for b in bars),
                    close=bars[-1].close,
                    volume=None,
                    provider=MOCK_PROVIDER,
                    ingested_at=INGESTED_AT,
                )
            )
        return ProviderChunk(candles, {"mock": True})
