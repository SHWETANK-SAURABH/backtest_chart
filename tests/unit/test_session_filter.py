"""Excluding provider prints outside session hours (test candles shaped like the real ones)."""

from datetime import date, datetime

from app.data.ingestion.normalize import to_frame
from app.data.ingestion.session_filter import keep_session_bars
from app.domain.candle import EXCHANGE_TZ
from tests.support.mock_market_data import mock_candle, mock_session_candles


def at(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=EXCHANGE_TZ)


DAY = date(2022, 3, 24)


def test_pre_open_and_closing_prints_are_excluded_and_counted() -> None:
    candles = [
        mock_candle(at(DAY, 9, 10)),
        *mock_session_candles(DAY),
        mock_candle(at(DAY, 15, 30)),
    ]
    kept, result = keep_session_bars(to_frame(candles))
    assert kept.height == 75
    assert result.excluded == 2
    assert result.by_time == {"09:10": 1, "15:30": 1}
    assert result.samples == [at(DAY, 9, 10).isoformat(), at(DAY, 15, 30).isoformat()]


def test_late_closing_prints_are_excluded() -> None:
    day = date(2025, 4, 25)
    candles = [
        *mock_session_candles(day),
        mock_candle(at(day, 15, 35)),
        mock_candle(at(day, 15, 55)),
    ]
    kept, result = keep_session_bars(to_frame(candles))
    assert kept.height == 75
    assert result.by_time == {"15:35": 1, "15:55": 1}


def test_muhurat_session_candles_are_kept() -> None:
    day = date(2024, 11, 1)  # scheduled 18:00 to 19:00
    candles = [mock_candle(at(day, 18, 5 * i)) for i in range(12)]  # 18:00 to 18:55
    kept, result = keep_session_bars(to_frame(candles))
    assert kept.height == 12
    assert result.excluded == 0


def test_dates_without_a_scheduled_session_keep_everything() -> None:
    saturday = date(2025, 2, 1)  # budget-day session, absent from the calendar
    candles = [mock_candle(at(saturday, 9, 10)), mock_candle(at(saturday, 9, 15))]
    kept, result = keep_session_bars(to_frame(candles))
    assert kept.height == 2
    assert result.excluded == 0


def test_empty_frame() -> None:
    kept, result = keep_session_bars(to_frame([]))
    assert kept.is_empty()
    assert result.excluded == 0
