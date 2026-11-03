"""The MTZ reversal strategy: indicator context from the Pine script plus the owner's entry rules.

Entry rules confirmed by the owner on 2026-11-02:
- Zones are the daily and weekly MTZ, the CPR band between BC and TC.
- Enter on a reversal candle (OR, DR, ER, WR) at an MTZ.
- Target the next MTZ in the trade direction.
- Stop at the signal candle's low (long) or high (short).
- The trade direction panel does not gate entries.

Added by the owner on 2026-11-03:
- Each backtest chooses which patterns may enter and which MTZ (daily, weekly or both) entries
  come from. Targets may be any other MTZ, daily or weekly.
- Once price touches the daily R2 or S2, no new entries for the rest of the session.
- The daily CPR histogram sets the exit: Sideways means no trades that day; Sideways Trading
  targets the next MTZ; Trending and Possible Trending have no target and exit when a candle of
  the opposite colour closes beyond the fast (5) EMA, applied by the backtesting engine.

Added by the owner later on 2026-11-03, each a backtest option:
- The CPR width thresholds that set the histogram can differ from the script's 0.25/0.50/0.75%.
- Day direction: the 2-day CPR relationship and opening bias allow only longs or only shorts.
  Where they give no direction, a 15-minute close beyond the daily CPR sets it.
- ADR trade: on days that are not Trending or Possible Trending, once the session's range reaches
  the ADR, one trade against the move that completed it, targeting the next MTZ. ADR sets that
  day's volatility, so this trade is not blocked by R2/S2, day direction or a Sideways histogram.

Detailed choices made where the rules were silent are listed in docs/strategy.md.

Candles are processed one at a time and the engine holds no reference to later candles, so a
decision can only depend on the past.
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.domain.candle import EXCHANGE_TZ
from app.domain.enums import DecisionAction
from app.strategy.adr import DailyAdr, adr_state
from app.strategy.hot_zones import HotZone, detect_hot_zones, hot_zone_breakouts, is_near
from app.strategy.levels import (
    HIST_POSSIBLE,
    HIST_SIDEWAYS,
    HIST_SIDEWAYS_TRADE,
    HIST_TRENDING,
    PeriodBar,
    histogram,
)
from app.strategy.parameters import StrategyParameters
from app.strategy.periods import Period, PeriodAggregator, PeriodLevels
from app.strategy.pine import Ema, is_na
from app.strategy.reasons import explain
from app.strategy.reversal import Bar, ReversalDetector, ReversalSignal
from app.strategy.trade_direction import BIAS_BEAR, BIAS_BULL, map_bias, trade_direction

DIRECTION_FROM_BIAS = "opening_bias"
DIRECTION_FROM_BREAK = "cpr_break_15m"


@dataclass(frozen=True)
class SessionInfo:
    """What is legitimately known about the current session when its bars are evaluated."""

    trading_date: date
    open: float
    open_source: str  # "daily_candle" or "first_intraday_bar"


@dataclass(frozen=True)
class Zone:
    name: str  # "daily_mtz" or "weekly_mtz"
    top: float  # TC
    bottom: float  # BC

    def touched_by(self, bar: Bar) -> bool:
        """f_isInRange on TC, BC or PP, or the bar inside the band: equivalent to overlap."""
        return bar.low <= self.top and bar.high >= self.bottom


@dataclass(frozen=True)
class EntrySignal:
    side: str  # "long" or "short"
    patterns: list[str]
    touched_zones: list[str]
    signal_candle_high: float
    signal_candle_low: float
    stop_loss: float
    # None when the exit is the EMA trail rather than a target.
    target: float | None
    target_zone: str | None
    exit_mode: str  # EXIT_MTZ_TARGET or EXIT_EMA_TRAIL


@dataclass
class Decision:
    timestamp: datetime
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    action: DecisionAction
    reason_codes: list[str]
    explanation: str
    signal: EntrySignal | None
    context: dict[str, Any] = field(default_factory=dict)


def _finite(value: float) -> float | None:
    return None if math.isnan(value) else value


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    """NaN becomes None, so context serialises to valid JSON."""
    return {
        key: _clean(value)
        if isinstance(value, dict)
        else _finite(value)
        if isinstance(value, float)
        else value
        for key, value in data.items()
    }


class MtzReversalStrategy:
    def __init__(
        self, parameters: StrategyParameters | None = None, bar: timedelta = timedelta(minutes=5)
    ) -> None:
        self.parameters = parameters or StrategyParameters()
        self._bar = bar
        self._aggregators = {period: PeriodAggregator(period) for period in Period}
        self._adr = DailyAdr(self.parameters.adr_length)
        self._reversals = ReversalDetector()
        self._ema_fast = Ema(self.parameters.ema_fast_length)
        self._ema_slow = Ema(self.parameters.ema_slow_length)
        self._previous_slow = math.nan
        self._previous_close = math.nan
        self._previous_bar: Bar | None = None
        self._session: SessionInfo | None = None
        self._last_completed: date | None = None
        self._levels: dict[Period, PeriodLevels] = {}
        self._session_high = math.nan
        self._session_low = math.nan
        self._hot_zones: list[HotZone] = []
        self._mtz_zones: list[Zone] = []
        self._target_zones: list[Zone] = []
        self._extreme_reached = False
        self._histogram = HIST_SIDEWAYS_TRADE
        self._day_side: str | None = None
        self._day_source: str | None = None
        self._adr_done = False
        self._session_context: dict[str, Any] = {}

    def add_completed_session(self, trading_date: date, bar: PeriodBar) -> None:
        """Record a finished session's daily candle, between sessions and in date order."""
        if self._last_completed is not None and trading_date <= self._last_completed:
            raise ValueError(f"Daily candles must be added in date order; got {trading_date}")
        for aggregator in self._aggregators.values():
            aggregator.add_day(trading_date, bar)
        self._adr.add_session(bar.high, bar.low)
        self._last_completed = trading_date

    def start_session(self, session: SessionInfo) -> None:
        # Every daily candle known to the strategy must be from an earlier session.
        if self._last_completed is not None and self._last_completed >= session.trading_date:
            raise ValueError(
                f"Session {session.trading_date} would see the daily candle "
                f"of {self._last_completed}"
            )
        self._session = session
        self._levels = {
            period: aggregator.levels_for(session.trading_date, session.open)
            for period, aggregator in self._aggregators.items()
        }
        self._session_high = math.nan
        self._session_low = math.nan

        # Levels, hot zones and the trade direction panel are fixed for the whole session, so
        # they are computed and serialised once here rather than on every candle.
        day, week = self._levels[Period.DAY], self._levels[Period.WEEK]
        self._hot_zones = detect_hot_zones(
            day,
            week,
            self._levels[Period.MONTH],
            self._levels[Period.YEAR],
            self.parameters.hot_zone_tolerance,
            self.parameters.hot_zone_min_score,
        )
        self._mtz_zones = self._zones(self.parameters.mtz_periods)
        self._target_zones = self._zones((Period.DAY, Period.WEEK))
        self._extreme_reached = False
        self._adr_done = False
        # The backtest's own thresholds; NaN width (no history) falls through to Sideways Trading.
        self._histogram = histogram(day.cpr.width_percent, self.parameters.cpr_thresholds)
        self._day_side = {BIAS_BULL: "long", BIAS_BEAR: "short"}.get(map_bias(day.cpr.bias))
        self._day_source = DIRECTION_FROM_BIAS if self._day_side else None
        self._session_context = _clean(
            {
                "session_open": session.open,
                "session_open_source": session.open_source,
                "cpr_daily": {**day.cpr.to_dict(), "histogram": self._histogram},
                "cpr_weekly": week.cpr.to_dict(),
                "camarilla_daily": day.camarilla.to_dict(),
                "trade_direction": trade_direction(day.cpr, week.cpr, session.open).to_dict(),
                "hot_zone_list": [zone.to_dict() for zone in self._hot_zones],
            }
        )

    def on_bar(
        self,
        timestamp: datetime,
        bar: Bar,
        final_bar_of_session: bool = False,
        session_daily_candle: PeriodBar | None = None,
    ) -> Decision:
        """Evaluate a confirmed bar. On the final bar the session's daily candle may be passed,
        because the session is complete at that bar's close."""
        if self._session is None:
            raise RuntimeError("start_session must be called first")
        session = self._session
        day = self._levels[Period.DAY]

        self._session_high = (
            bar.high if is_na(self._session_high) else max(self._session_high, bar.high)
        )
        self._session_low = bar.low if is_na(self._session_low) else min(self._session_low, bar.low)
        adr_value = self._adr.value
        if final_bar_of_session and session_daily_candle is not None:
            adr_value = self._adr.value_including(
                session_daily_candle.high, session_daily_candle.low
            )
        adr = adr_state(
            adr_value, session.open, self._session_high, self._session_low, self._adr.message
        )

        ema_fast = self._ema_fast.update(bar.close)
        ema_slow = self._ema_slow.update(bar.close)
        ema_direction = None
        if not is_na(self._previous_slow):
            ema_direction = (
                "rising"
                if ema_slow > self._previous_slow
                else "falling"
                if ema_slow < self._previous_slow
                else "flat"
            )

        signals = self._reversals.update(bar)
        # Known at this bar's close, so it already blocks a signal confirmed on this bar.
        if (not is_na(day.cpr.r2) and bar.high >= day.cpr.r2) or (
            not is_na(day.cpr.s2) and bar.low <= day.cpr.s2
        ):
            self._extreme_reached = True
        # Without a direction from the opening bias, the latest 15-minute close beyond the CPR
        # sets it; that close is known at this bar's close.
        if self._day_source != DIRECTION_FROM_BIAS and self._closes_15m(timestamp):
            if bar.close > day.cpr.tc:
                self._day_side, self._day_source = "long", DIRECTION_FROM_BREAK
            elif bar.close < day.cpr.bc:
                self._day_side, self._day_source = "short", DIRECTION_FROM_BREAK
        h4_break, l4_break = hot_zone_breakouts(
            self._hot_zones, day.camarilla.h4, day.camarilla.l4, bar.close, self._previous_close
        )

        allowed = [s for s in signals if s.code in self.parameters.entry_patterns]
        action, codes, entry = self._adr_reversal(bar) or self._decide(bar, allowed)
        shared = self._session_context
        context = _clean(
            {
                "adr": adr.to_dict(),
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "ema_slow_direction": ema_direction,
                "price_vs_ema_slow": None
                if is_na(ema_slow)
                else (
                    "above" if bar.close > ema_slow else "below" if bar.close < ema_slow else "at"
                ),
                "cpr_position": _position(bar.close, day.cpr.tc, day.cpr.bc),
                "day_direction": {"side": self._day_side, "source": self._day_source},
                "hot_zones": {"h4_breakout": h4_break, "l4_breakdown": l4_break},
                "reversal_signals": [
                    {"code": s.code, "side": "long" if s.is_long else "short"} for s in signals
                ],
                "magnet_trade": _magnet(
                    session.open,
                    day,
                    self._previous_day_close(),
                    adr_value,
                    self.parameters.magnet_min_gap,
                ),
            }
        )
        # Session-wide values are shared, read-only, by every candle's context in the session.
        context = {
            "session_open": shared["session_open"],
            "session_open_source": shared["session_open_source"],
            "cpr_daily": shared["cpr_daily"],
            "cpr_weekly": shared["cpr_weekly"],
            "camarilla_daily": shared["camarilla_daily"],
            "trade_direction": shared["trade_direction"],
            **context,
        }
        context["hot_zones"] = {"zones": shared["hot_zone_list"], **context["hot_zones"]}
        self._previous_close = bar.close
        self._previous_slow = ema_slow
        self._previous_bar = bar
        return Decision(
            timestamp=timestamp,
            trading_date=session.trading_date,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            action=action,
            reason_codes=codes,
            explanation=explain(codes, entry),
            signal=entry,
            context=context,
        )

    def _previous_day_close(self) -> float:
        # The daily Camarilla center is the previous session's close.
        return self._levels[Period.DAY].camarilla.center

    def _zones(self, periods: tuple[Period, ...]) -> list[Zone]:
        names = {Period.DAY: "daily_mtz", Period.WEEK: "weekly_mtz"}
        zones = []
        for period in periods:
            cpr = self._levels[period].cpr
            if not is_na(cpr.tc) and not is_na(cpr.bc):
                zones.append(Zone(names[period], cpr.tc, cpr.bc))
        return zones

    def _closes_15m(self, timestamp: datetime) -> bool:
        """Whether this bar's close is also a 15-minute candle's close."""
        return (timestamp + self._bar).astimezone(EXCHANGE_TZ).minute % 15 == 0

    def _adr_reversal(
        self, bar: Bar
    ) -> tuple[DecisionAction, list[str], EntrySignal | None] | None:
        """The ADR trade, on the bar where the session's range first reaches the ADR."""
        adr = self._adr.value
        if (
            not self.parameters.adr_trade
            or self._adr_done
            or self._histogram in (HIST_TRENDING, HIST_POSSIBLE)
            or is_na(adr)
            or self._session_high - self._session_low < adr
        ):
            return None
        self._adr_done = True
        made_high = bar.high >= self._session_high
        made_low = bar.low <= self._session_low
        if made_high == made_low:
            return DecisionAction.HOLD, ["ADR_COMPLETE", "ADR_DIRECTION_UNCLEAR"], None
        # The move that completed the ADR was down, so the trade is long, and the reverse.
        is_long = made_low
        codes = ["ADR_COMPLETE", "ADR_LONG" if is_long else "ADR_SHORT"]
        if is_long:
            stop = bar.low
            candidates = [z for z in self._target_zones if z.bottom > bar.close]
            target_zone = min(candidates, key=lambda z: z.bottom, default=None)
            stop_valid = stop < bar.close
        else:
            stop = bar.high
            candidates = [z for z in self._target_zones if z.top < bar.close]
            target_zone = max(candidates, key=lambda z: z.top, default=None)
            stop_valid = stop > bar.close
        if target_zone is None:
            return DecisionAction.HOLD, ["NO_TARGET_ZONE", *codes], None
        if not stop_valid:
            return DecisionAction.HOLD, ["INVALID_STOP", *codes], None
        entry = EntrySignal(
            side="long" if is_long else "short",
            patterns=["ADR"],
            touched_zones=[],
            signal_candle_high=bar.high,
            signal_candle_low=bar.low,
            stop_loss=stop,
            target=target_zone.bottom if is_long else target_zone.top,
            target_zone=target_zone.name,
            exit_mode="EXIT_MTZ_TARGET",
        )
        action = DecisionAction.BUY if is_long else DecisionAction.SELL
        return action, [*codes, f"TARGET_{target_zone.name.upper()}", "EXIT_MTZ_TARGET"], entry

    def _decide(
        self, bar: Bar, signals: list[ReversalSignal]
    ) -> tuple[DecisionAction, list[str], EntrySignal | None]:
        zones = self._mtz_zones
        if not zones:
            return DecisionAction.HOLD, ["NO_MTZ_LEVELS"], None
        if not signals:
            return DecisionAction.HOLD, ["NO_REVERSAL_SIGNAL"], None
        patterns = _pattern_codes(signals)
        if self._histogram == HIST_SIDEWAYS:
            return DecisionAction.HOLD, ["CPR_SIDEWAYS_NO_TRADE", *patterns], None
        if self._extreme_reached:
            return DecisionAction.HOLD, ["R2_S2_REACHED", *patterns], None

        # Proximity is tested on the bar before the confirming bar, as the script's labels do.
        reference = self._previous_bar
        if reference is None:
            return DecisionAction.HOLD, ["REVERSAL_NOT_AT_MTZ", *patterns], None
        touched = [zone for zone in zones if zone.touched_by(reference)]
        if not touched:
            return DecisionAction.HOLD, ["REVERSAL_NOT_AT_MTZ", *patterns], None
        # Any zone the signal touched, from either period, is where the trade starts.
        targets = [zone for zone in self._target_zones if not zone.touched_by(reference)]
        trail = self._histogram in (HIST_TRENDING, HIST_POSSIBLE)

        sides = {signal.is_long for signal in signals}
        if len(sides) > 1:
            return DecisionAction.HOLD, ["CONFLICTING_SIGNALS", *patterns], None
        is_long = sides.pop()
        codes = [*patterns, *(f"AT_{z.name.upper()}" for z in touched)]
        if self.parameters.day_direction:
            if self._day_side is None:
                return DecisionAction.HOLD, ["NO_DAY_DIRECTION", *codes], None
            if self._day_side != ("long" if is_long else "short"):
                return DecisionAction.HOLD, ["AGAINST_DAY_DIRECTION", *codes], None
            codes.append(f"DAY_DIRECTION_{(self._day_source or '').upper()}")

        # With several patterns on one bar, the widest signal candle sets the stop.
        if is_long:
            stop = min(signal.signal_bar.low for signal in signals)
            candidates = [z for z in targets if z.bottom > bar.close]
            target_zone = min(candidates, key=lambda z: z.bottom, default=None)
            target = target_zone.bottom if target_zone else None
            stop_valid = stop < bar.close
        else:
            stop = max(signal.signal_bar.high for signal in signals)
            candidates = [z for z in targets if z.top < bar.close]
            target_zone = max(candidates, key=lambda z: z.top, default=None)
            target = target_zone.top if target_zone else None
            stop_valid = stop > bar.close

        if trail:
            target_zone, target = None, None
        elif target_zone is None:
            return DecisionAction.HOLD, ["NO_TARGET_ZONE", *codes], None
        if not stop_valid:
            return DecisionAction.HOLD, ["INVALID_STOP", *codes], None
        exit_mode = "EXIT_EMA_TRAIL" if trail else "EXIT_MTZ_TARGET"

        entry = EntrySignal(
            side="long" if is_long else "short",
            patterns=sorted({signal.code for signal in signals}),
            touched_zones=[zone.name for zone in touched],
            signal_candle_high=max(signal.signal_bar.high for signal in signals),
            signal_candle_low=min(signal.signal_bar.low for signal in signals),
            stop_loss=stop,
            target=target,
            target_zone=target_zone.name if target_zone else None,
            exit_mode=exit_mode,
        )
        action = DecisionAction.BUY if is_long else DecisionAction.SELL
        exit_codes = [f"TARGET_{target_zone.name.upper()}"] if target_zone else []
        return action, [*codes, *exit_codes, exit_mode], entry


def _pattern_codes(signals: list[ReversalSignal]) -> list[str]:
    return sorted({f"{s.code}_{'LONG' if s.is_long else 'SHORT'}" for s in signals})


def _position(price: float, tc: float, bc: float) -> str | None:
    if is_na(tc) or is_na(bc):
        return None
    if price > tc:
        return "above_tc"
    if price < bc:
        return "below_bc"
    return "inside_cpr"


def _magnet(
    session_open: float, day: PeriodLevels, prior_close: float, adr_value: float, min_gap: float
) -> bool:
    """isMagnetTrade (strategy.pine 1108-1112). Informational, and off by default in the script."""
    cpr = day.cpr
    gap_up = session_open > cpr.tc
    gap_down = session_open < cpr.bc
    within = (gap_up and session_open <= cpr.r2) or (gap_down and session_open >= cpr.s2)
    return bool(
        within and not is_na(adr_value) and abs(session_open - prior_close) >= adr_value * min_gap
    )


__all__ = ["Decision", "EntrySignal", "MtzReversalStrategy", "SessionInfo", "is_near"]
