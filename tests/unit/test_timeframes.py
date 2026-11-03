"""Building 15-minute candles from 5-minute candles (test values only)."""

from datetime import date, datetime, timedelta

import polars as pl
import pytest

from app.backtesting.timeframes import resample
from app.domain.candle import EXCHANGE_TZ
from app.domain.enums import Timeframe

DAY = date(2025, 6, 16)


def five_minute(count: int, start_hour: int = 9, start_minute: int = 15) -> pl.DataFrame:
    start = datetime(DAY.year, DAY.month, DAY.day, start_hour, start_minute, tzinfo=EXCHANGE_TZ)
    return pl.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * i) for i in range(count)],
            "trading_date": [DAY] * count,
            "open": [100.0 + i for i in range(count)],
            "high": [101.0 + i for i in range(count)],
            "low": [99.0 + i for i in range(count)],
            "close": [100.5 + i for i in range(count)],
        }
    ).with_columns(pl.col("timestamp").dt.convert_time_zone("UTC"))


def local_times(frame: pl.DataFrame) -> list[str]:
    return [t.astimezone(EXCHANGE_TZ).strftime("%H:%M") for t in frame["timestamp"]]


def test_a_full_session_becomes_25_candles_from_0915() -> None:
    candles = resample(five_minute(75), Timeframe.M15)
    assert candles.height == 25
    assert local_times(candles)[:2] == ["09:15", "09:30"]
    assert local_times(candles)[-1] == "15:15"


def test_ohlc_comes_from_the_three_parts() -> None:
    first = resample(five_minute(3), Timeframe.M15).row(0, named=True)
    assert (first["open"], first["high"], first["low"], first["close"]) == (100, 103, 99, 102.5)


def test_incomplete_groups_are_dropped() -> None:
    frame = five_minute(6).filter(pl.col("open") != 104.0)  # remove the 09:35 candle
    assert local_times(resample(frame, Timeframe.M15)) == ["09:15"]


def test_special_sessions_on_quarter_hours_align() -> None:
    assert local_times(resample(five_minute(12, 18, 0), Timeframe.M15)) == [
        "18:00",
        "18:15",
        "18:30",
        "18:45",
    ]


def test_five_minute_data_is_returned_unchanged() -> None:
    frame = five_minute(3)
    assert resample(frame, Timeframe.M5) is frame


def test_daily_cannot_be_built_from_intraday() -> None:
    with pytest.raises(ValueError):
        resample(five_minute(3), Timeframe.D1)
