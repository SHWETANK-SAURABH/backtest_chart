"""Pivot Boss setups from "Secrets of a Pivot Boss", a backtest choice next to the MTZ reversal.

Sources: the owner's port (prompt/book.txt) and summary of the book (prompt/mainbook.txt). The
owner chose on 2026-11-03 to follow the book summary where the two differ, and settled the points
the book leaves open:
- Narrow and wide days come from the CPR histogram with the backtest's thresholds.
- A rejected open fades the CPR: a reversal candle at the CPR, stop at that candle, target S1/R1.
- Breakaway targets R3/S3 with a 1.5 ATR trailing stop. Floor pivot targets R1/S1. Magnet trades
  target the CPR with no time exit.
Other choices are listed in docs/pivot-boss.md.

Levels, reversal candles and the candle context come from the MTZ strategy; only the entry
decision differs. Every input is known at the confirming candle's close.
"""

import math
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from app.domain.candle import EXCHANGE_TZ
from app.domain.enums import DecisionAction
from app.strategy.engine import EntrySignal, MtzReversalStrategy, SessionInfo, _magnet
from app.strategy.levels import HIST_POSSIBLE, HIST_TRENDING, PeriodBar, cpr_band
from app.strategy.periods import Period
from app.strategy.pine import Sma, is_na
from app.strategy.reversal import Bar, ReversalSignal

ATR_LENGTH = 14
ATR_TRAIL_MULTIPLIER = 1.5
# The book's CPR pull-back is a morning trade; book.txt allows the first 8 bars after the first.
EARLY_SESSION_END = time(11, 15)
# Gap fills usually happen within 30 to 60 minutes, so the magnet's reversal must come early.
MAGNET_WINDOW_END = time(10, 15)
EXIT_FIXED_TARGET = "EXIT_FIXED_TARGET"
EXIT_ATR_TRAIL = "EXIT_ATR_TRAIL"
UP_RELATIONSHIPS = ("higher", "higher_overlapping")
DOWN_RELATIONSHIPS = ("lower", "lower_overlapping")


@dataclass(frozen=True)
class Candidate:
    setup: str
    is_long: bool
    stop: float
    target: float
    target_name: str
    zone: str
    triggers: tuple[str, ...] = ()
    trail: bool = False


def _bias(close: float, top: float, bottom: float) -> int:
    """+1 if a close finished above its own CPR, -1 below, 0 inside or unknown."""
    if is_na(close) or is_na(top) or is_na(bottom):
        return 0
    return 1 if close > top else -1 if close < bottom else 0


class PivotBossStrategy(MtzReversalStrategy):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._true_ranges = Sma(ATR_LENGTH)
        self._atr = math.nan
        self._last_close = math.nan
        self._daily_bias = 0
        self._previous_daily_bias = 0
        self._weekly_bias = 0
        self._session_bars: deque[Bar] = deque()
        # Each completed day's close against its own CPR, from the daily candles alone.
        self._day_biases: deque[int] = deque([0, 0], maxlen=2)
        self._last_day: PeriodBar | None = None

    def add_completed_session(self, trading_date: date, bar: PeriodBar) -> None:
        super().add_completed_session(trading_date, bar)
        tc, bc = cpr_band(self._last_day)
        self._day_biases.append(_bias(bar.close, tc, bc))
        self._last_day = bar

    def start_session(self, session: SessionInfo) -> None:
        super().start_session(session)
        week = self._levels[Period.WEEK]
        self._previous_daily_bias, self._daily_bias = self._day_biases
        # The weekly Camarilla center is the previous week's close.
        self._weekly_bias = _bias(week.camarilla.center, week.prev_tc, week.prev_bc)
        self._session_bars = deque()

    def _extra_context(self) -> dict[str, Any]:
        cpr = self._levels[Period.DAY].cpr
        session = self._session
        assert session is not None
        return {
            "pivot_boss": {
                "daily_bias": self._daily_bias,
                "previous_daily_bias": self._previous_daily_bias,
                "weekly_bias": self._weekly_bias,
                "open_rejects_bias": self._rejected(session.open, cpr.tc, cpr.bc),
                "narrow_day": self._narrow,
                "atr": self._atr,
            },
            "atr_trail": {
                "long": self._last_close - ATR_TRAIL_MULTIPLIER * self._atr,
                "short": self._last_close + ATR_TRAIL_MULTIPLIER * self._atr,
            },
        }

    @property
    def _narrow(self) -> bool:
        return self._histogram in (HIST_TRENDING, HIST_POSSIBLE)

    def _rejected(self, session_open: float, tc: float, bc: float) -> bool:
        return (self._daily_bias == 1 and session_open <= bc) or (
            self._daily_bias == -1 and session_open >= tc
        )

    def _entry(
        self, timestamp: datetime, bar: Bar, signals: list[ReversalSignal]
    ) -> tuple[DecisionAction, list[str], EntrySignal | None]:
        # ta.atr-style true range across sessions, averaged as book.txt does.
        previous_close = self._last_close
        true_range = (
            bar.high - bar.low
            if is_na(previous_close)
            else max(
                bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)
            )
        )
        self._atr = self._true_ranges.update(true_range)
        self._last_close = bar.close
        try:
            return self._choose(timestamp, bar, signals)
        finally:
            self._session_bars.append(bar)

    def _choose(
        self, timestamp: datetime, bar: Bar, signals: list[ReversalSignal]
    ) -> tuple[DecisionAction, list[str], EntrySignal | None]:
        day = self._levels[Period.DAY]
        cpr, cam = day.cpr, day.camarilla
        if any(is_na(v) for v in (cpr.tc, cpr.bc, cpr.r1, cpr.s1, cam.h3, cam.l3)):
            return DecisionAction.HOLD, ["NO_LEVELS"], None

        closes_at = (timestamp + self._bar).astimezone(EXCHANGE_TZ).time()
        finders = {
            "BREAKAWAY": self._breakaway,
            "MAGNET": self._magnet_fill,
            "CPR_PULLBACK": self._cpr_pullback,
            "CPR_FADE": self._cpr_fade,
            "FLOOR_PIVOT": self._floor_pivot,
            "CAM_REVERSAL": self._cam_reversal,
            "CAM_BREAKOUT": self._cam_breakout,
        }
        blocked: list[str] = []
        for setup in self.parameters.book_setups:
            for candidate in finders[setup](bar, signals, closes_at):
                if self.parameters.weekly_filter and (
                    (candidate.is_long and self._weekly_bias < 0)
                    or (not candidate.is_long and self._weekly_bias > 0)
                ):
                    blocked.append("AGAINST_WEEKLY_BIAS")
                    continue
                if (candidate.is_long and candidate.stop >= bar.close) or (
                    not candidate.is_long and candidate.stop <= bar.close
                ):
                    blocked.append("INVALID_STOP")
                    continue
                if (candidate.is_long and candidate.target <= bar.close) or (
                    not candidate.is_long and candidate.target >= bar.close
                ):
                    blocked.append("NO_ROOM_TO_TARGET")
                    continue
                return self._enter(candidate, bar)
        return DecisionAction.HOLD, [blocked[0] if blocked else "NO_BOOK_SETUP"], None

    def _enter(
        self, c: Candidate, bar: Bar
    ) -> tuple[DecisionAction, list[str], EntrySignal | None]:
        side = "LONG" if c.is_long else "SHORT"
        exit_mode = EXIT_ATR_TRAIL if c.trail else EXIT_FIXED_TARGET
        entry = EntrySignal(
            side="long" if c.is_long else "short",
            patterns=[c.setup],
            touched_zones=[c.zone],
            signal_candle_high=bar.high,
            signal_candle_low=bar.low,
            stop_loss=c.stop,
            target=c.target,
            target_zone=c.target_name,
            exit_mode=exit_mode,
        )
        codes = [
            f"{c.setup}_{side}",
            *(f"TRIGGER_{t}" for t in c.triggers),
            f"TARGET_{c.target_name.upper()}",
            exit_mode,
        ]
        return (DecisionAction.BUY if c.is_long else DecisionAction.SELL), codes, entry

    # Each finder returns the setup's long and short candidates on this candle, if any.

    def _breakaway(self, bar: Bar, signals: list[ReversalSignal], at: time) -> list[Candidate]:
        """Narrow CPR; the open gaps beyond the prior range and R1/S1 but not past R2/S2; the
        first candle tests the passed pivot and holds. Stop at the day's extreme."""
        if self._session_bars or not self._narrow:
            return []
        cpr, session = self._levels[Period.DAY].cpr, self._session
        assert session is not None
        o = session.open
        found = []
        if o > cpr.ph and cpr.r1 < o <= cpr.r2 and bar.low <= cpr.r1 < bar.close:
            found.append(Candidate("BREAKAWAY", True, bar.low, cpr.r3, "r3", "r1", trail=True))
        if o < cpr.pl and cpr.s2 <= o < cpr.s1 and bar.high >= cpr.s1 > bar.close:
            found.append(Candidate("BREAKAWAY", False, bar.high, cpr.s3, "s3", "s1", trail=True))
        return found

    def _magnet_fill(self, bar: Bar, signals: list[ReversalSignal], at: time) -> list[Candidate]:
        """The script's magnet gap; a reversal candle toward the CPR in the first hour. Stop at
        the day's extreme, target the CPR's near edge."""
        day, session = self._levels[Period.DAY], self._session
        assert session is not None
        if at > MAGNET_WINDOW_END or not _magnet(
            session.open,
            day,
            day.camarilla.center,
            self._adr.value,
            self.parameters.magnet_min_gap,
        ):
            return []
        cpr = day.cpr
        if session.open > cpr.tc:
            shorts = _codes(signals, False)
            if shorts:
                return [Candidate("MAGNET", False, self._session_high, cpr.tc, "tc", "gap", shorts)]
        else:
            longs = _codes(signals, True)
            if longs:
                return [Candidate("MAGNET", True, self._session_low, cpr.bc, "bc", "gap", longs)]
        return []

    def _cpr_pullback(self, bar: Bar, signals: list[ReversalSignal], at: time) -> list[Candidate]:
        """Bias confirmed by the open and a Higher/Lower Value relationship; an early test of the
        CPR with a reversal candle. Stop beyond the far side of the CPR, target R1/S1."""
        day, session = self._levels[Period.DAY], self._session
        assert session is not None
        cpr = day.cpr
        if at > EARLY_SESSION_END:
            return []
        found = []
        longs, shorts = _matching(signals, True), _matching(signals, False)
        if (
            self._daily_bias == 1
            and session.open > cpr.bc
            and cpr.relationship in UP_RELATIONSHIPS
            and longs
            and min(s.signal_bar.low for s in longs) <= cpr.tc < bar.close
        ):
            found.append(
                Candidate("CPR_PULLBACK", True, cpr.bc, cpr.r1, "r1", "cpr", _names(longs))
            )
        if (
            self._daily_bias == -1
            and session.open < cpr.tc
            and cpr.relationship in DOWN_RELATIONSHIPS
            and shorts
            and max(s.signal_bar.high for s in shorts) >= cpr.bc > bar.close
        ):
            found.append(
                Candidate("CPR_PULLBACK", False, cpr.tc, cpr.s1, "s1", "cpr", _names(shorts))
            )
        return found

    def _cpr_fade(self, bar: Bar, signals: list[ReversalSignal], at: time) -> list[Candidate]:
        """The open rejects the bias: a reversal candle at the CPR the other way. Stop at the
        reversal candle, target S1/R1."""
        session = self._session
        assert session is not None
        cpr = self._levels[Period.DAY].cpr
        if not self._rejected(session.open, cpr.tc, cpr.bc):
            return []
        if self._daily_bias == 1:
            shorts = _matching(signals, False)
            if shorts and max(s.signal_bar.high for s in shorts) >= cpr.bc > bar.close:
                stop = max(s.signal_bar.high for s in shorts)
                return [Candidate("CPR_FADE", False, stop, cpr.s1, "s1", "cpr", _names(shorts))]
        else:
            longs = _matching(signals, True)
            if longs and min(s.signal_bar.low for s in longs) <= cpr.tc < bar.close:
                stop = min(s.signal_bar.low for s in longs)
                return [Candidate("CPR_FADE", True, stop, cpr.r1, "r1", "cpr", _names(longs))]
        return []

    def _floor_pivot(self, bar: Bar, signals: list[ReversalSignal], at: time) -> list[Candidate]:
        """An established trend (the prior two closes on the same side of their CPRs): a reversal
        candle at the CPR or S1 (up) / R1 (down). Stop beyond the level, target R1/S1."""
        cpr = self._levels[Period.DAY].cpr
        if self._daily_bias == 1 and self._previous_daily_bias == 1:
            longs = _matching(signals, True)
            if longs:
                low = min(s.signal_bar.low for s in longs)
                if low <= cpr.tc < bar.close:
                    return [
                        Candidate("FLOOR_PIVOT", True, cpr.bc, cpr.r1, "r1", "cpr", _names(longs))
                    ]
                if low <= cpr.s1 < bar.close:
                    stop = min(cpr.s1, low)
                    return [Candidate("FLOOR_PIVOT", True, stop, cpr.r1, "r1", "s1", _names(longs))]
        if self._daily_bias == -1 and self._previous_daily_bias == -1:
            shorts = _matching(signals, False)
            if shorts:
                high = max(s.signal_bar.high for s in shorts)
                if high >= cpr.bc > bar.close:
                    return [
                        Candidate("FLOOR_PIVOT", False, cpr.tc, cpr.s1, "s1", "cpr", _names(shorts))
                    ]
                if high >= cpr.r1 > bar.close:
                    stop = max(cpr.r1, high)
                    return [
                        Candidate("FLOOR_PIVOT", False, stop, cpr.s1, "s1", "r1", _names(shorts))
                    ]
        return []

    def _cam_reversal(self, bar: Bar, signals: list[ReversalSignal], at: time) -> list[Candidate]:
        """A wick through L3 (H3) closing back inside, then a confirming candle that stays on the
        right side and closes beyond the prior close. Stop at L4 (H4), target H3 (L3)."""
        if not self._session_bars:
            return []
        prev, cam = self._session_bars[-1], self._levels[Period.DAY].camarilla
        found = []
        if (
            self._daily_bias >= 0
            and prev.low <= cam.l3 < prev.close
            and bar.low > cam.l3
            and bar.close > prev.close
        ):
            found.append(Candidate("CAM_REVERSAL", True, cam.l4, cam.h3, "h3", "l3"))
        if (
            self._daily_bias <= 0
            and prev.high >= cam.h3 > prev.close
            and bar.high < cam.h3
            and bar.close < prev.close
        ):
            found.append(Candidate("CAM_REVERSAL", False, cam.h4, cam.l3, "l3", "h3"))
        return found

    def _cam_breakout(self, bar: Bar, signals: list[ReversalSignal], at: time) -> list[Candidate]:
        """After at least one failed test of H4 (L4) today, the first close beyond it that is also
        beyond the earlier tests' highs (lows). Stop at H3 (L3), target H5 (L5)."""
        if not self._session_bars:
            return []
        cam = self._levels[Period.DAY].camarilla
        prev = self._session_bars[-1]
        found = []
        up_tests = [b.high for b in self._session_bars if b.high >= cam.h4 > b.close]
        if up_tests and prev.close <= cam.h4 < bar.close and bar.close > max(up_tests):
            found.append(Candidate("CAM_BREAKOUT", True, cam.h3, cam.h5, "h5", "h4"))
        down_tests = [b.low for b in self._session_bars if b.low <= cam.l4 < b.close]
        if down_tests and prev.close >= cam.l4 > bar.close and bar.close < min(down_tests):
            found.append(Candidate("CAM_BREAKOUT", False, cam.l3, cam.l5, "l5", "l4"))
        return found


def _matching(signals: list[ReversalSignal], is_long: bool) -> list[ReversalSignal]:
    return [s for s in signals if s.is_long == is_long]


def _names(signals: list[ReversalSignal]) -> tuple[str, ...]:
    return tuple(sorted({s.code for s in signals}))


def _codes(signals: list[ReversalSignal], is_long: bool) -> tuple[str, ...]:
    return _names(_matching(signals, is_long))
