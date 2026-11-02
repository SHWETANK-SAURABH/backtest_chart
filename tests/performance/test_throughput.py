"""Throughput of the strategy and engine on a year of synthetic candles.

Excluded by default; run with: pytest -m performance. Timings depend on the machine, so the limit is
generous: it catches an accidental slowdown of several times, not small variations.
"""

import time
from datetime import date

import pytest

from app.backtesting.engine import BacktestEngine
from app.data.ingestion.normalize import to_frame
from app.strategy.runner import iter_evaluations
from tests.support.mock_market_data import RandomWalkProvider

pytestmark = pytest.mark.performance

# Measured at 3.6 seconds (about 5,000 candles a second) on the development machine.
ONE_YEAR_LIMIT_SECONDS = 20


def test_one_year_of_five_minute_candles() -> None:
    provider = RandomWalkProvider()
    instrument = provider.resolve_instrument("NIFTY50")
    intraday = to_frame(
        provider.get_historical_candles(
            instrument, "5m", date(2024, 1, 1), date(2024, 12, 31)
        ).candles
    )
    daily = to_frame(
        provider.get_daily_candles(instrument, date(2023, 6, 1), date(2024, 12, 31)).candles
    )

    started = time.perf_counter()
    result = BacktestEngine().run(iter_evaluations(intraday, daily))
    elapsed = time.perf_counter() - started

    assert len(result.records) == intraday.height
    print(f"\n{intraday.height} candles in {elapsed:.1f}s ({intraday.height / elapsed:,.0f}/s)")
    assert elapsed < ONE_YEAR_LIMIT_SECONDS
