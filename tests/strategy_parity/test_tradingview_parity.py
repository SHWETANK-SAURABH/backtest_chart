"""Compare Python levels with values exported from TradingView on identical candles.

Skipped until exports are placed in tests/strategy_parity/fixtures/. See the README there.
"""

import math
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from app.domain.candle import EXCHANGE_TIMEZONE
from app.strategy.runner import evaluate

FIXTURES = Path(__file__).parent / "fixtures"
# Index levels move in ticks of 0.05; anything closer is a match.
TOLERANCE = 0.01

# TradingView plot title -> (context section, field). Titles come from the plot() calls.
PLOTS = {
    "TC": ("cpr_daily", "tc"),
    "PP": ("cpr_daily", "pp"),
    "BC": ("cpr_daily", "bc"),
    "R1": ("cpr_daily", "r1"),
    "R2": ("cpr_daily", "r2"),
    "R3": ("cpr_daily", "r3"),
    "R4": ("cpr_daily", "r4"),
    "S1": ("cpr_daily", "s1"),
    "S2": ("cpr_daily", "s2"),
    "S3": ("cpr_daily", "s3"),
    "S4": ("cpr_daily", "s4"),
    "PH": ("cpr_daily", "ph"),
    "PL": ("cpr_daily", "pl"),
    "Cam-Central": ("camarilla_daily", "center"),
    "Cam-H3": ("camarilla_daily", "h3"),
    "Cam-H4": ("camarilla_daily", "h4"),
    "Cam-H5": ("camarilla_daily", "h5"),
    "Cam-H6": ("camarilla_daily", "h6"),
    "Cam-L3": ("camarilla_daily", "l3"),
    "Cam-L4": ("camarilla_daily", "l4"),
    "Cam-L5": ("camarilla_daily", "l5"),
    "Cam-L6": ("camarilla_daily", "l6"),
    "EMA 1": (None, "ema_fast"),
    "EMA 2": (None, "ema_slow"),
}


def _load(path: Path) -> pl.DataFrame:
    frame = pl.read_csv(path)
    timestamps = [datetime.fromtimestamp(int(t), tz=UTC) for t in frame["time"]]
    return frame.with_columns(
        timestamp=pl.Series(timestamps, dtype=pl.Datetime("us", "UTC")),
    ).with_columns(
        trading_date=pl.col("timestamp").dt.convert_time_zone(EXCHANGE_TIMEZONE).dt.date()
    )


def _pairs() -> list[tuple[Path, Path]]:
    return [
        (intraday, intraday.with_name(intraday.name.replace("_5m.csv", "_1d.csv")))
        for intraday in sorted(FIXTURES.glob("*_5m.csv"))
    ]


@pytest.mark.skipif(not _pairs(), reason="no TradingView exports in fixtures/")
@pytest.mark.parametrize(("intraday_path", "daily_path"), _pairs() or [(None, None)])
def test_levels_match_tradingview(intraday_path: Path, daily_path: Path) -> None:
    intraday = _load(intraday_path)
    daily = _load(daily_path)
    decisions = evaluate(intraday, daily)

    compared = 0
    mismatches = []
    for row, decision in zip(intraday.iter_rows(named=True), decisions, strict=True):
        for plot, (section, field) in PLOTS.items():
            expected = row.get(plot)
            if expected is None or (isinstance(expected, float) and math.isnan(expected)):
                continue
            source = decision.context[section] if section else decision.context
            actual = source[field]
            compared += 1
            if actual is None or abs(actual - expected) > TOLERANCE:
                mismatches.append(
                    f"{row['timestamp']} {plot}: TradingView {expected}, Python {actual}"
                )

    assert compared > 0, "the export contains none of the expected plot columns"
    assert not mismatches, f"{len(mismatches)} of {compared} values differ:\n" + "\n".join(
        mismatches[:25]
    )
