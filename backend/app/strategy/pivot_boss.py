"""Pivot Boss setups from "Secrets of a Pivot Boss", a backtest choice next to the MTZ reversal.

Sources: the owner's port (prompt/book.txt) and summary of the book (prompt/mainbook.txt). The
owner chose on 2026-11-03 to follow the book summary where the two differ, and settled the points
the book leaves open:
- Narrow and wide days come from the CPR histogram with the backtest's thresholds.
- A rejected open fades the CPR: a reversal candle at the CPR, stop at that candle, target S1/R1.
- Breakaway targets R3/S3 with a 1.5 ATR trailing stop. Floor pivot targets R1/S1. Magnet trades
  target the CPR with no time exit.

Added by the owner on 2026-11-04 (implementation 5.0.0):
- Full trend analysis, an option that gates every setup. The day's sides come from the 7 two-day
  relationships as the book reads them, flipped when the open rejects them. The floor-pivot trend
  (a daily close beyond S1 or R1 flips it) and the weekly trend must agree or be neutral.
- Camarilla pattern setup: a reversal pattern at a Camarilla level, with the CPR width picking the
  play. Wide days fade H3/L3 to the opposite level; narrow days buy L3/L4 (sell H3/H4) and trail
  with the 5 EMA.
- John Person's trend plan: in the S1/R1 trend, a reversal pattern at S1 or the CPR (R1 or the
  CPR when down), target R1 (S1).
- Trend-change play: after a strong day (close at a 5-day high, range at least the ADR), a wick
  reversal at the CPR the next morning, target R1. Mirrored after a strong down day.
- Clear trend only, an option: trend setups need the S1/R1 trend, the day's relationship side and
  the weekly trend all on their side ("the market trends only about 30% of the time").
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
EXIT_EMA_TRAIL = "EXIT_EMA_TRAIL"
LONG, SHORT = "long", "short"
UP_RELATIONSHIPS = ("higher", "higher_overlapping")
DOWN_RELATIONSHIPS = ("lower", "lower_overlapping")
# Setups that trade with the trend; "clear trend only" applies to these.
TREND_SETUPS = ("BREAKAWAY", "CPR_PULLBACK", "PERSON_PLAN", "FLOOR_PIVOT", "CAM_BREAKOUT")
STRONG_DAY_LOOKBACK = 5


@dataclass(frozen=True)
class Candidate:
    setup: str
    is_long: bool
    stop: float
    target: float | None  # None: exit on the 5 EMA trail
    target_name: str
    zone: str
    triggers: tuple[str, ...] = ()
    trail: bool = False


def _direction(score: int) -> str | None:
    return LONG if score > 0 else SHORT if score < 0 else None


def _relationship_score(relationship: str) -> int:
    return (
        1 if relationship in UP_RELATIONSHIPS else -1 if relationship in DOWN_RELATIONSHIPS else 0
    )


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
        # Floor-pivot trend: holds while daily closes stay beyond the first layer (S1 up, R1 down).
        self._pivot_trend: str | None = None
        # Full trend analysis: sides allowed today, a side allowed only on a strong signal, and
        # whether the side waits for the first 15-minute close beyond the CPR (Inside Value).
        self._sides: set[str] = {LONG, SHORT}
        self._strong_side: str | None = None
        self._await_break = False
        self._weekly_trend: str | None = None
        # For the trend-change play: recent closes and the last day's range.
        self._recent_closes: deque[float] = deque(maxlen=STRONG_DAY_LOOKBACK)
        self._last_range = math.nan
        self._strong_day: str | None = None

    def add_completed_session(self, trading_date: date, bar: PeriodBar) -> None:
        super().add_completed_session(trading_date, bar)
        tc, bc = cpr_band(self._last_day)
        self._day_biases.append(_bias(bar.close, tc, bc))
        self._recent_closes.append(bar.close)
        self._last_range = bar.high - bar.low
        if self._last_day is not None:
            # The completed day's own S1 and R1, from the day before it.
            prior = self._last_day
            pivot = (prior.high + prior.low + prior.close) / 3
            r1, s1 = 2 * pivot - prior.low, 2 * pivot - prior.high
            if self._pivot_trend == LONG and bar.close < s1:
                self._pivot_trend = SHORT
            elif self._pivot_trend == SHORT and bar.close > r1:
                self._pivot_trend = LONG
            elif self._pivot_trend is None:
                self._pivot_trend = LONG if bar.close > r1 else SHORT if bar.close < s1 else None
        self._last_day = bar

    def start_session(self, session: SessionInfo) -> None:
        super().start_session(session)
        week = self._levels[Period.WEEK]
        self._previous_daily_bias, self._daily_bias = self._day_biases
        # The weekly Camarilla center is the previous week's close.
        self._weekly_bias = _bias(week.camarilla.center, week.prev_tc, week.prev_bc)
        self._weekly_trend = _direction(
            self._weekly_bias + _relationship_score(week.cpr.relationship)
        )
        self._session_bars = deque()
        self._set_day_sides(session.open)
        # A strong day: closed at the highest (lowest) of the last 5 closes with a range of at
        # least the ADR, which includes that day.
        closes, adr = self._recent_closes, self._adr.value
        self._strong_day = None
        if len(closes) == STRONG_DAY_LOOKBACK and not is_na(adr) and self._last_range >= adr:
            if closes[-1] >= max(closes):
                self._strong_day = LONG
            elif closes[-1] <= min(closes):
                self._strong_day = SHORT

    def _set_day_sides(self, session_open: float) -> None:
        """The book's reading of the 7 two-day relationships, flipped by a rejecting open."""
        cpr = self._levels[Period.DAY].cpr
        self._strong_side, self._await_break = None, False
        relationship = cpr.relationship
        if relationship in UP_RELATIONSHIPS + DOWN_RELATIONSHIPS:
            up = relationship in UP_RELATIONSHIPS
            # Higher Value opening below BC (Lower Value above TC) rejects it: the side flips.
            rejected = session_open < cpr.bc if up else session_open > cpr.tc
            side = (LONG if up else SHORT) if not rejected else (SHORT if up else LONG)
            self._sides = {side}
            if relationship.endswith("_overlapping") and not rejected:
                self._strong_side = SHORT if up else LONG
        elif relationship == "outside":
            self._sides = {LONG, SHORT}
        elif relationship == "inside":
            self._sides, self._await_break = set(), True
        else:  # unchanged: the open decides
            self._sides = (
                {LONG} if session_open > cpr.tc else {SHORT} if session_open < cpr.bc else set()
            )

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
                "trend": {
                    "day_sides": sorted(self._sides),
                    "strong_signal_side": self._strong_side,
                    "awaiting_cpr_break": self._await_break,
                    "pivot_trend": self._pivot_trend,
                    "weekly_trend": self._weekly_trend,
                },
                "strong_day": self._strong_day,
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
        # Inside Value: the first 15-minute close beyond the CPR sets the breakout side.
        cpr = self._levels[Period.DAY].cpr
        if self._await_break and self._closes_15m(timestamp):
            if bar.close > cpr.tc:
                self._sides, self._await_break = {LONG}, False
            elif bar.close < cpr.bc:
                self._sides, self._await_break = {SHORT}, False
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
            "TREND_CHANGE": self._trend_change,
            "PERSON_PLAN": self._person_plan,
            "FLOOR_PIVOT": self._floor_pivot,
            "CAM_REVERSAL": self._cam_reversal,
            "CAM_PATTERN": self._cam_pattern,
            "CAM_BREAKOUT": self._cam_breakout,
        }
        blocked: list[str] = []
        for setup in self.parameters.book_setups:
            for candidate in finders[setup](bar, signals, closes_at):
                if (
                    self.parameters.clear_trend
                    and candidate.setup in TREND_SETUPS
                    and not self._clear_trend(candidate)
                ):
                    blocked.append("TREND_NOT_CLEAR")
                    continue
                if self.parameters.trend_analysis:
                    against = self._against_trend(candidate)
                    if against:
                        blocked.append(against)
                        continue
                elif self.parameters.weekly_filter and (
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
                target = candidate.target
                if target is not None and (
                    (candidate.is_long and target <= bar.close)
                    or (not candidate.is_long and target >= bar.close)
                ):
                    blocked.append("NO_ROOM_TO_TARGET")
                    continue
                return self._enter(candidate, bar)
        return DecisionAction.HOLD, [blocked[0] if blocked else "NO_BOOK_SETUP"], None

    def _clear_trend(self, c: Candidate) -> bool:
        side = LONG if c.is_long else SHORT
        return self._sides == {side} and self._pivot_trend == side and self._weekly_trend == side

    def _against_trend(self, c: Candidate) -> str | None:
        """Why full trend analysis blocks a candidate, or None when it may trade."""
        side = LONG if c.is_long else SHORT
        strong = side == self._strong_side and len(c.triggers) >= 2
        if side not in self._sides and not strong:
            return "AGAINST_DAY_TREND"
        if self._pivot_trend not in (None, side):
            return "AGAINST_PIVOT_TREND"
        if self._weekly_trend not in (None, side):
            return "AGAINST_WEEKLY_TREND"
        return None

    def _enter(
        self, c: Candidate, bar: Bar
    ) -> tuple[DecisionAction, list[str], EntrySignal | None]:
        side = "LONG" if c.is_long else "SHORT"
        if c.target is None:
            exit_mode = EXIT_EMA_TRAIL
        else:
            exit_mode = EXIT_ATR_TRAIL if c.trail else EXIT_FIXED_TARGET
        entry = EntrySignal(
            side="long" if c.is_long else "short",
            patterns=[c.setup],
            touched_zones=[c.zone],
            signal_candle_high=bar.high,
            signal_candle_low=bar.low,
            stop_loss=c.stop,
            target=c.target,
            target_zone=c.target_name if c.target is not None else None,
            exit_mode=exit_mode,
        )
        codes = [
            f"{c.setup}_{side}",
            *(f"TRIGGER_{t}" for t in c.triggers),
            *([f"TARGET_{c.target_name.upper()}"] if c.target is not None else []),
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

    def _trend_change(self, bar: Bar, signals: list[ReversalSignal], at: time) -> list[Candidate]:
        """After a strong day, the next morning's dip to the CPR on a wick reversal. Stop at the
        wick candle, target R1 (S1 after a strong down day)."""
        if self._strong_day is None or at > EARLY_SESSION_END:
            return []
        cpr = self._levels[Period.DAY].cpr
        if self._strong_day == LONG:
            wicks = [s for s in _matching(signals, True) if s.code == "WR"]
            if wicks and min(s.signal_bar.low for s in wicks) <= cpr.tc < bar.close:
                stop = min(s.signal_bar.low for s in wicks)
                return [Candidate("TREND_CHANGE", True, stop, cpr.r1, "r1", "cpr", ("WR",))]
        else:
            wicks = [s for s in _matching(signals, False) if s.code == "WR"]
            if wicks and max(s.signal_bar.high for s in wicks) >= cpr.bc > bar.close:
                stop = max(s.signal_bar.high for s in wicks)
                return [Candidate("TREND_CHANGE", False, stop, cpr.s1, "s1", "cpr", ("WR",))]
        return []

    def _person_plan(self, bar: Bar, signals: list[ReversalSignal], at: time) -> list[Candidate]:
        """John Person's filter: in the S1/R1 uptrend only S1 and the CPR are buy zones, target
        R1; in the downtrend only R1 and the CPR are sell zones, target S1."""
        cpr = self._levels[Period.DAY].cpr
        if self._pivot_trend == LONG:
            longs = _matching(signals, True)
            if longs:
                low = min(s.signal_bar.low for s in longs)
                if low <= cpr.tc < bar.close:
                    return [
                        Candidate("PERSON_PLAN", True, cpr.bc, cpr.r1, "r1", "cpr", _names(longs))
                    ]
                if low <= cpr.s1 < bar.close:
                    stop = min(cpr.s1, low)
                    return [Candidate("PERSON_PLAN", True, stop, cpr.r1, "r1", "s1", _names(longs))]
        if self._pivot_trend == SHORT:
            shorts = _matching(signals, False)
            if shorts:
                high = max(s.signal_bar.high for s in shorts)
                if high >= cpr.bc > bar.close:
                    return [
                        Candidate("PERSON_PLAN", False, cpr.tc, cpr.s1, "s1", "cpr", _names(shorts))
                    ]
                if high >= cpr.r1 > bar.close:
                    stop = max(cpr.r1, high)
                    return [
                        Candidate("PERSON_PLAN", False, stop, cpr.s1, "s1", "r1", _names(shorts))
                    ]
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

    def _cam_pattern(self, bar: Bar, signals: list[ReversalSignal], at: time) -> list[Candidate]:
        """A reversal pattern at a Camarilla level, the play picked by the CPR width.

        Wide day (range): long at L3 (stop L4, target H3), short at H3 (stop H4, target L3).
        Narrow day (trend): long at L3 (stop L4) or L4 (stop L5), short at H3 (stop H4) or H4
        (stop H5), with no target and the 5 EMA trail.
        """
        cam = self._levels[Period.DAY].camarilla
        longs, shorts = _matching(signals, True), _matching(signals, False)
        found = []
        if longs:
            low = min(s.signal_bar.low for s in longs)
            if self._narrow and low <= cam.l4 < bar.close:
                found.append(Candidate("CAM_PATTERN", True, cam.l5, None, "", "l4", _names(longs)))
            elif low <= cam.l3 < bar.close:
                target = None if self._narrow else cam.h3
                found.append(
                    Candidate("CAM_PATTERN", True, cam.l4, target, "h3", "l3", _names(longs))
                )
        if shorts:
            high = max(s.signal_bar.high for s in shorts)
            if self._narrow and high >= cam.h4 > bar.close:
                found.append(
                    Candidate("CAM_PATTERN", False, cam.h5, None, "", "h4", _names(shorts))
                )
            elif high >= cam.h3 > bar.close:
                target = None if self._narrow else cam.l3
                found.append(
                    Candidate("CAM_PATTERN", False, cam.h4, target, "l3", "h3", _names(shorts))
                )
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
