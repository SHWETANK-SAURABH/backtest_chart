"""Calendar, chunking, de-duplication and validation. All candles are clearly labelled mocks."""

import itertools
from datetime import date, datetime, timedelta

import polars as pl
import pytest

from app.data.calendar import nse
from app.data.ingestion.chunking import plan_chunks
from app.data.ingestion.normalize import deduplicate, to_frame
from app.data.ingestion.validation import validate_candles
from app.domain.candle import EXCHANGE_TZ
from app.domain.enums import Timeframe
from tests.support.mock_market_data import mock_candle, mock_daily_candle, mock_session_candles

DAY = date(2025, 6, 16)
BAR = datetime(2025, 6, 16, 9, 15, tzinfo=EXCHANGE_TZ)


def test_regular_session_has_75_five_minute_bars() -> None:
    session = nse.sessions(DAY, DAY)[0]
    bars = nse.expected_bar_opens(session)
    assert len(bars) == 75
    assert bars[0] == BAR
    assert bars[-1].hour == 15
    assert bars[-1].minute == 25


def test_weekends_and_holidays_have_no_session() -> None:
    assert nse.sessions(date(2025, 6, 14), date(2025, 6, 15)) == []
    assert nse.sessions(date(2026, 1, 26), date(2026, 1, 26)) == []


def test_years_without_holiday_data_are_flagged_as_unverified() -> None:
    assert nse.holidays_verified(date(2026, 12, 31))
    assert not nse.holidays_verified(date(2027, 1, 1))


def test_library_holiday_coverage_constant_is_current() -> None:
    weekdays = 261
    populated = len(nse.sessions(date(2026, 1, 1), date(2026, 12, 31)))
    assert populated < weekdays - 5


@pytest.mark.parametrize(
    ("end", "max_days", "expected"),
    [
        (date(2025, 1, 1), 90, 1),
        (date(2025, 3, 31), 90, 1),
        (date(2025, 4, 1), 90, 2),
        (date(2025, 12, 31), 90, 5),
    ],
)
def test_chunks_cover_the_range_without_overlap(end: date, max_days: int, expected: int) -> None:
    start = date(2025, 1, 1)
    chunks = plan_chunks(start, end, max_days)
    assert len(chunks) == expected
    assert chunks[0][0] == start
    assert chunks[-1][1] == end
    for (_, previous_end), (next_start, _) in itertools.pairwise(chunks):
        assert next_start == previous_end + timedelta(days=1)
    assert all((e - s).days < max_days for s, e in chunks)


def test_invalid_chunk_arguments_raise() -> None:
    with pytest.raises(ValueError):
        plan_chunks(date(2025, 1, 2), date(2025, 1, 1), 90)
    with pytest.raises(ValueError):
        plan_chunks(date(2025, 1, 1), date(2025, 1, 2), 0)


def test_trading_date_uses_exchange_time_not_utc() -> None:
    # Daily candles at IST midnight are the previous date in UTC.
    frame = to_frame([mock_daily_candle(DAY)])
    assert frame["trading_date"][0] == DAY
    assert frame["timestamp"][0].date() == DAY - timedelta(days=1)


def test_exact_duplicates_are_removed_and_conflicts_counted() -> None:
    frame = to_frame([mock_candle(BAR), mock_candle(BAR), mock_candle(BAR, price=200.0)])
    result, stats = deduplicate(frame)
    assert result.height == 1
    assert result["open"][0] == 100.0
    assert stats.exact_duplicates == 1
    assert stats.conflicting_duplicates == 1


def test_clean_session_has_no_issues() -> None:
    report = validate_candles(to_frame(mock_session_candles(DAY)), Timeframe.M5)
    assert report.row_count == 75
    assert not report.has_critical_issues
    assert report.missing_candles == 0
    assert report.first_date == report.last_date == DAY.isoformat()


def test_missing_candles_are_reported_by_time_without_being_critical() -> None:
    candles = mock_session_candles(DAY)
    del candles[10]
    report = validate_candles(to_frame(candles), Timeframe.M5)
    assert report.missing_candles == 1
    assert report.missing_by_date == {DAY.isoformat(): ["10:05"]}
    assert not report.has_critical_issues


def test_entire_missing_session_is_reported() -> None:
    candles = [*mock_session_candles(date(2025, 6, 16)), *mock_session_candles(date(2025, 6, 18))]
    report = validate_candles(to_frame(candles), Timeframe.M5)
    assert report.missing_sessions == ["2025-06-17"]
    assert report.missing_candles == 75


@pytest.mark.parametrize(
    "candle",
    [
        mock_candle(BAR, high=99.0),
        mock_candle(BAR, low=101.0),
        mock_candle(BAR, price=0.0, low=0.0),
    ],
)
def test_invalid_ohlc_is_critical(candle) -> None:
    report = validate_candles(to_frame([candle]), Timeframe.M5)
    assert report.invalid_ohlc == 1
    assert report.has_critical_issues


def test_misaligned_timestamp_is_critical() -> None:
    frame = to_frame([mock_candle(BAR + timedelta(minutes=2))])
    report = validate_candles(frame, Timeframe.M5)
    assert report.misaligned_timestamps == 1
    assert report.has_critical_issues


def test_utc_epoch_misread_as_local_would_be_caught() -> None:
    # Bars shifted by the IST offset land outside the session, marking the dataset invalid.
    frame = to_frame([mock_candle(BAR - timedelta(hours=5, minutes=30))])
    report = validate_candles(frame, Timeframe.M5)
    assert report.outside_session_bars == 1
    assert report.has_critical_issues


@pytest.mark.parametrize(
    "bar",
    [BAR - timedelta(minutes=5), BAR.replace(hour=15, minute=30)],
)
def test_bars_outside_the_session_are_critical(bar: datetime) -> None:
    report = validate_candles(to_frame([mock_candle(bar)]), Timeframe.M5)
    assert report.outside_session_bars == 1
    assert report.has_critical_issues


def test_data_on_a_special_session_is_kept_and_flagged() -> None:
    # Saturday 2025-02-01 traded, but the library's schedule omits it.
    saturday = datetime(2025, 2, 1, 9, 15, tzinfo=EXCHANGE_TZ)
    report = validate_candles(to_frame([mock_candle(saturday)]), Timeframe.M5)
    assert report.row_count == 1
    assert report.unscheduled_sessions == ["2025-02-01"]
    assert not report.has_critical_issues


def test_duplicate_rows_are_critical() -> None:
    report = validate_candles(to_frame([mock_candle(BAR), mock_candle(BAR)]), Timeframe.M5)
    assert report.duplicate_timestamps == 1
    assert report.has_critical_issues


def test_absent_volume_is_counted_not_treated_as_zero() -> None:
    frame = to_frame([mock_candle(BAR), mock_candle(BAR + timedelta(minutes=5), volume=10)])
    report = validate_candles(frame, Timeframe.M5)
    assert report.rows_with_volume == 1
    assert frame["volume"][0] is None


def test_daily_candles_validate_against_the_calendar() -> None:
    candles = [mock_daily_candle(date(2025, 6, 16)), mock_daily_candle(date(2025, 6, 18))]
    report = validate_candles(to_frame(candles), Timeframe.D1)
    assert report.missing_sessions == ["2025-06-17"]
    assert not report.has_critical_issues


def test_daily_candle_not_at_exchange_midnight_is_critical() -> None:
    report = validate_candles(to_frame([mock_candle(BAR, Timeframe.D1)]), Timeframe.D1)
    assert report.misaligned_timestamps == 1
    assert report.has_critical_issues


def test_empty_frame_is_handled() -> None:
    report = validate_candles(to_frame([]), Timeframe.M5)
    assert report.row_count == 0
    assert isinstance(to_frame([]), pl.DataFrame)
