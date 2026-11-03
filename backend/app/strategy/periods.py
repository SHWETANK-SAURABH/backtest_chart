"""Daily, weekly, monthly and yearly levels from completed daily candles.

This reproduces request.security(..., [open, high, low, close, open[1], ...], lookahead_on) as the
script uses it: a period's levels come from the previous completed period, and its open is known
from the period's first session. Only daily candles dated before the current session are ever
added, so no later information can reach a level.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.strategy.levels import (
    CamarillaLevels,
    CprLevels,
    PeriodBar,
    calculate_camarilla,
    calculate_cpr,
    camarilla_h3_l3,
    cpr_band,
)


class Period(StrEnum):
    DAY = "D"
    WEEK = "W"
    MONTH = "M"
    YEAR = "12M"


def period_key(day: date, period: Period) -> tuple[int, ...]:
    if period == Period.DAY:
        return (day.toordinal(),)
    if period == Period.WEEK:
        iso = day.isocalendar()  # Weeks start on Monday, as on TradingView.
        return (iso.year, iso.week)
    if period == Period.MONTH:
        return (day.year, day.month)
    return (day.year,)


@dataclass(frozen=True)
class PeriodLevels:
    period: Period
    open: float
    cpr: CprLevels
    camarilla: CamarillaLevels
    # The previous period's own CPR band, which the relationship compares against.
    prev_tc: float
    prev_bc: float


class PeriodAggregator:
    """Builds period bars from daily candles added in chronological order."""

    def __init__(self, period: Period) -> None:
        self.period = period
        self._keys: list[tuple[int, ...]] = []
        self._bars: list[PeriodBar] = []

    def add_day(self, day: date, bar: PeriodBar) -> None:
        key = period_key(day, self.period)
        if self._keys and key < self._keys[-1]:
            raise ValueError(f"Daily candles must be added in order; got {day}")
        if self._keys and self._keys[-1] == key:
            last = self._bars[-1]
            self._bars[-1] = PeriodBar(
                last.open, max(last.high, bar.high), min(last.low, bar.low), bar.close
            )
        else:
            self._keys.append(key)
            self._bars.append(bar)

    def levels_for(self, day: date, session_open: float) -> PeriodLevels:
        """Levels in force on `day`, given that day's session open."""
        key = period_key(day, self.period)
        if self._keys and self._keys[-1] == key:
            current_open = self._bars[-1].open
            completed = self._bars[:-1]
        else:
            current_open = session_open
            completed = self._bars
        previous = completed[-1] if completed else None
        before_previous = completed[-2] if len(completed) >= 2 else None

        prev_tc, prev_bc = cpr_band(before_previous)
        prev_h3, prev_l3 = camarilla_h3_l3(before_previous)
        return PeriodLevels(
            period=self.period,
            open=current_open,
            cpr=calculate_cpr(previous, current_open, prev_tc, prev_bc),
            camarilla=calculate_camarilla(previous, current_open, prev_h3, prev_l3),
            prev_tc=prev_tc,
            prev_bc=prev_bc,
        )
