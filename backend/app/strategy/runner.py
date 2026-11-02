"""Feeds stored candles to the strategy in strict chronological order."""

import hashlib
from datetime import timedelta
from pathlib import Path

import polars as pl

from app.data.calendar import nse
from app.domain.candle import EXCHANGE_TZ
from app.strategy.engine import Decision, MtzReversalStrategy, SessionInfo
from app.strategy.levels import PeriodBar
from app.strategy.parameters import StrategyParameters
from app.strategy.reversal import Bar

STRATEGY_SOURCE_DIR = Path(__file__).parent
_BAR = timedelta(minutes=nse.BAR_MINUTES)


def code_hash() -> str:
    """SHA-256 of the strategy package source, recorded with every strategy version."""
    digest = hashlib.sha256()
    for path in sorted(STRATEGY_SOURCE_DIR.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def evaluate(
    intraday: pl.DataFrame, daily: pl.DataFrame, parameters: StrategyParameters | None = None
) -> list[Decision]:
    """One decision per intraday candle.

    `daily` may extend beyond the intraday range. A daily candle is given to the strategy only once
    its session has ended; of the current session's daily candle, only the open is used before the
    final bar.
    """
    strategy = MtzReversalStrategy(parameters)
    daily_rows = {
        row["trading_date"]: row for row in daily.sort("trading_date").iter_rows(named=True)
    }
    daily_dates = sorted(daily_rows)
    next_daily = 0

    decisions = []
    current_date = None
    session_close = None
    for row in intraday.sort("timestamp").iter_rows(named=True):
        day = row["trading_date"]
        if day != current_date:
            while next_daily < len(daily_dates) and daily_dates[next_daily] < day:
                completed = daily_rows[daily_dates[next_daily]]
                strategy.add_completed_session(
                    daily_dates[next_daily],
                    PeriodBar(
                        completed["open"], completed["high"], completed["low"], completed["close"]
                    ),
                )
                next_daily += 1
            today = daily_rows.get(day)
            strategy.start_session(
                SessionInfo(day, today["open"], "daily_candle")
                if today is not None
                else SessionInfo(day, row["open"], "first_intraday_bar")
            )
            sessions = nse.sessions(day, day)
            session_close = sessions[0].close if sessions else None
            current_date = day

        local_open = row["timestamp"].astimezone(EXCHANGE_TZ)
        final_bar = session_close is not None and local_open + _BAR == session_close
        today = daily_rows.get(day)
        decisions.append(
            strategy.on_bar(
                row["timestamp"],
                Bar(row["open"], row["high"], row["low"], row["close"]),
                final_bar_of_session=final_bar,
                session_daily_candle=(
                    PeriodBar(today["open"], today["high"], today["low"], today["close"])
                    if final_bar and today is not None
                    else None
                ),
            )
        )
    return decisions
