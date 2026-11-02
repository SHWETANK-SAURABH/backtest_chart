"""Keeps 5-minute candles within each scheduled session's hours.

Providers can return reference prints outside regular trading: Upstox returned a flat 09:10 candle
at the pre-open auction price and a flat 15:30 candle at the official close on every session from
24 March to 22 July 2022, and flat 15:35 and 15:55 candles on several days in 2025. They are not
traded candles, and TradingView's NIFTY chart shows only the regular session, so they are excluded
from published datasets. The official open and close remain in the daily candles. Every excluded
candle is counted in the quality report, and the provider's original payload is kept under raw/.

Dates with no scheduled session (such as budget-day weekend sessions) keep all their candles.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta

import polars as pl

from app.data.calendar import nse
from app.domain.candle import EXCHANGE_TZ

SAMPLE_LIMIT = 20


@dataclass
class SessionFilterResult:
    excluded: int = 0
    by_time: dict[str, int] = field(default_factory=dict)
    samples: list[str] = field(default_factory=list)


def keep_session_bars(frame: pl.DataFrame) -> tuple[pl.DataFrame, SessionFilterResult]:
    """Candles inside their session's hours, and a record of the ones left out."""
    if frame.is_empty():
        return frame, SessionFilterResult()
    first, last = frame["trading_date"].min(), frame["trading_date"].max()
    schedule = {s.trading_date: s for s in nse.sessions(first, last)}  # type: ignore[arg-type]
    bar = timedelta(minutes=nse.BAR_MINUTES)

    keep = []
    excluded = []
    for day, moment in zip(frame["trading_date"].to_list(), frame["timestamp"].to_list(), strict=True):
        session = schedule.get(day)
        local = moment.astimezone(EXCHANGE_TZ)
        inside = session is None or session.open <= local <= session.close - bar
        keep.append(inside)
        if not inside:
            excluded.append(local)

    result = SessionFilterResult(
        excluded=len(excluded),
        by_time=dict(sorted(Counter(t.strftime("%H:%M") for t in excluded).items())),
        samples=[t.isoformat() for t in sorted(excluded)[:SAMPLE_LIMIT]],
    )
    return frame.filter(pl.Series(keep, dtype=pl.Boolean)), result
