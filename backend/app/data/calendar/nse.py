"""NSE trading sessions and holidays.

The schedule comes from pandas_market_calendars. Two limits are handled explicitly:

- Its holiday list stops at a known year. Later dates are reported as unverified, so holidays
  would not be mistaken for missing data.
- It omits some special sessions, such as the Saturday budget session of 2025-02-01. Data on such
  a date is kept and reported as an unscheduled session, never discarded.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache

import pandas_market_calendars as pmc

from app.domain.candle import EXCHANGE_TZ

# The last year for which the library contains NSE holidays. Check when upgrading it.
HOLIDAYS_POPULATED_THROUGH = 2026
BAR_MINUTES = 5


@dataclass(frozen=True)
class Session:
    trading_date: date
    open: datetime
    close: datetime


@lru_cache(maxsize=1)
def _calendar() -> pmc.MarketCalendar:
    return pmc.get_calendar("NSE")


def holidays_verified(day: date) -> bool:
    return day.year <= HOLIDAYS_POPULATED_THROUGH


def sessions(start: date, end: date) -> list[Session]:
    """Scheduled sessions for an inclusive range, with exchange-local times."""
    schedule = _calendar().schedule(start.isoformat(), end.isoformat())
    return [
        Session(
            trading_date=label.date(),
            open=row["market_open"].to_pydatetime().astimezone(EXCHANGE_TZ),
            close=row["market_close"].to_pydatetime().astimezone(EXCHANGE_TZ),
        )
        for label, row in schedule.iterrows()
    ]


def expected_bar_opens(session: Session) -> list[datetime]:
    """Open times of the 5-minute bars in a session."""
    step = timedelta(minutes=BAR_MINUTES)
    bars = []
    current = session.open
    while current < session.close:
        bars.append(current)
        current += step
    return bars
