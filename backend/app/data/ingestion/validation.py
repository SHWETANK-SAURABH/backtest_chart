"""Data quality checks. They report problems and never alter or remove data."""

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

import polars as pl

from app.data.calendar import nse
from app.domain.candle import EXCHANGE_TIMEZONE, EXCHANGE_TZ
from app.domain.enums import Timeframe

SAMPLE_LIMIT = 20


@dataclass
class QualityReport:
    timeframe: str
    row_count: int
    first_date: str | None = None
    last_date: str | None = None
    invalid_ohlc: int = 0
    invalid_ohlc_samples: list[str] = field(default_factory=list)
    duplicate_timestamps: int = 0
    conflicting_duplicates: int = 0
    misaligned_timestamps: int = 0
    misaligned_samples: list[str] = field(default_factory=list)
    outside_session_bars: int = 0
    outside_session_samples: list[str] = field(default_factory=list)
    unscheduled_sessions: list[str] = field(default_factory=list)
    missing_candles: int = 0
    missing_by_date: dict[str, list[str]] = field(default_factory=dict)
    missing_sessions: list[str] = field(default_factory=list)
    unverified_calendar_dates: bool = False
    rows_with_volume: int = 0
    revised_candles: int = 0
    excluded_incomplete_candles: int = 0
    # Provider prints outside session hours (such as pre-open and closing-price candles), left out
    # of the dataset before validation; see ingestion/session_filter.py.
    excluded_outside_session_candles: int = 0
    excluded_outside_session_by_time: dict[str, int] = field(default_factory=dict)
    excluded_outside_session_samples: list[str] = field(default_factory=list)

    @property
    def has_critical_issues(self) -> bool:
        """Whether a backtest must not use this data until someone has looked at it."""
        return bool(
            self.invalid_ohlc
            or self.duplicate_timestamps
            or self.conflicting_duplicates
            or self.misaligned_timestamps
            or self.outside_session_bars
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "has_critical_issues": self.has_critical_issues}


def validate_candles(
    frame: pl.DataFrame, timeframe: Timeframe, conflicting_duplicates: int = 0
) -> QualityReport:
    report = QualityReport(
        timeframe=timeframe.value,
        row_count=frame.height,
        conflicting_duplicates=conflicting_duplicates,
    )
    if frame.is_empty():
        return report

    first: date = frame["trading_date"].min()  # type: ignore[assignment]
    last: date = frame["trading_date"].max()  # type: ignore[assignment]
    report.first_date = first.isoformat()
    report.last_date = last.isoformat()
    report.unverified_calendar_dates = not nse.holidays_verified(last)
    report.rows_with_volume = frame["volume"].drop_nulls().len()
    report.duplicate_timestamps = frame.height - frame["timestamp"].n_unique()

    local = frame.with_columns(pl.col("timestamp").dt.convert_time_zone(EXCHANGE_TIMEZONE).alias("local"))
    _check_ohlc(local, report)
    if timeframe == Timeframe.D1:
        _check_daily(local, first, last, report)
    else:
        _check_intraday(local, first, last, report)
    return report


def _samples(frame: pl.DataFrame) -> list[str]:
    return [value.isoformat() for value in frame["local"].head(SAMPLE_LIMIT)]


def _check_ohlc(local: pl.DataFrame, report: QualityReport) -> None:
    bad = local.filter(
        (pl.col("high") < pl.max_horizontal("open", "close", "low"))
        | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
        | (pl.min_horizontal("open", "high", "low", "close") <= 0)
    )
    report.invalid_ohlc = bad.height
    report.invalid_ohlc_samples = _samples(bad)


def _check_daily(local: pl.DataFrame, first: date, last: date, report: QualityReport) -> None:
    # Daily candles are expected at exchange-local midnight.
    time_of_day = pl.col("local").dt.time()
    misaligned = local.filter(time_of_day != pl.time(0, 0))
    report.misaligned_timestamps = misaligned.height
    report.misaligned_samples = _samples(misaligned)

    scheduled = {session.trading_date for session in nse.sessions(first, last)}
    actual = set(local["trading_date"].to_list())
    report.unscheduled_sessions = sorted(day.isoformat() for day in actual - scheduled)
    missing = scheduled - actual
    report.missing_sessions = sorted(day.isoformat() for day in missing)
    report.missing_candles = len(missing)


def _check_intraday(local: pl.DataFrame, first: date, last: date, report: QualityReport) -> None:
    misaligned = local.filter(
        (pl.col("local").dt.minute() % nse.BAR_MINUTES != 0)
        | (pl.col("local").dt.second() != 0)
        | (pl.col("local").dt.microsecond() != 0)
    )
    report.misaligned_timestamps = misaligned.height
    report.misaligned_samples = _samples(misaligned)

    schedule = {session.trading_date: session for session in nse.sessions(first, last)}
    bars_by_date: dict[date, set[Any]] = {}
    for day, ts in zip(local["trading_date"].to_list(), local["local"].to_list(), strict=True):
        bars_by_date.setdefault(day, set()).add(ts.astimezone(EXCHANGE_TZ))

    report.unscheduled_sessions = sorted(
        day.isoformat() for day in bars_by_date.keys() - schedule.keys()
    )

    outside: list[str] = []
    for day, bars in bars_by_date.items():
        session = schedule.get(day)
        if session is not None:
            last_open = session.close - timedelta(minutes=nse.BAR_MINUTES)
            outside.extend(
                bar.isoformat() for bar in sorted(bars) if not session.open <= bar <= last_open
            )
    report.outside_session_bars = len(outside)
    report.outside_session_samples = sorted(outside)[:SAMPLE_LIMIT]

    for day, session in sorted(schedule.items()):
        expected = nse.expected_bar_opens(session)
        actual = bars_by_date.get(day)
        if actual is None:
            report.missing_sessions.append(day.isoformat())
            report.missing_candles += len(expected)
            continue
        gaps = [bar for bar in expected if bar not in actual]
        if gaps:
            report.missing_by_date[day.isoformat()] = [bar.strftime("%H:%M") for bar in gaps]
            report.missing_candles += len(gaps)
