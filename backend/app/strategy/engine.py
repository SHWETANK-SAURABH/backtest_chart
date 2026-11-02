"""The MTZ reversal strategy: indicator context from the Pine script plus the owner's entry rules.

Entry rules confirmed by the owner on 2026-11-02:
- Zones are the daily and weekly MTZ, the CPR band between BC and TC.
- Enter on a reversal candle (OR, DR, ER, WR) at an MTZ.
- Target the next MTZ in the trade direction.
- Stop at the signal candle's low (long) or high (short).
- The trade direction panel does not gate entries.

Detailed choices made where the rules were silent are listed in docs/strategy.md.

Candles are processed one at a time and the engine holds no reference to later candles, so a
decision can only depend on the past.
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.domain.enums import DecisionAction
from app.strategy.adr import DailyAdr, adr_state
from app.strategy.hot_zones import detect_hot_zones, hot_zone_breakouts, is_near
from app.strategy.levels import PeriodBar
from app.strategy.parameters import StrategyParameters
from app.strategy.periods import Period, PeriodAggregator, PeriodLevels
from app.strategy.pine import Ema, is_na
from app.strategy.reasons import explain
from app.strategy.reversal import Bar, ReversalDetector, ReversalSignal
from app.strategy.trade_direction import trade_direction


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
    target: float
    target_zone: str


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
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        self.parameters = parameters or StrategyParameters()
        self._aggregators = {period: PeriodAggregator(period) for period in Period}
        self._adr = DailyAdr(self.parameters.adr_length)
        self._reversals = ReversalDetector()
        self._ema_fast = Ema(self.parameters.ema_fast_length)
        self._ema_slow = Ema(self.parameters.ema_slow_length)
        self._previous_slow = math.nan
        self._previous_close = math.nan
        self._previous_bar: Bar | None = None
        self._session: SessionInfo | None = None
        self._levels: dict[Period, PeriodLevels] = {}
        self._session_high = math.nan
        self._session_low = math.nan

    def add_completed_session(self, trading_date: date, bar: PeriodBar) -> None:
        """Record a finished session's daily candle. Must precede the next session's bars."""
        if self._session is not None and trading_date >= self._session.trading_date:
            raise ValueError("A session's daily candle can only be added after the session")
        for aggregator in self._aggregators.values():
            aggregator.add_day(trading_date, bar)
        self._adr.add_session(bar.high, bar.low)

    def start_session(self, session: SessionInfo) -> None:
        self._session = session
        self._levels = {
            period: aggregator.levels_for(session.trading_date, session.open)
            for period, aggregator in self._aggregators.items()
        }
        self._session_high = math.nan
        self._session_low = math.nan

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
        day, week = self._levels[Period.DAY], self._levels[Period.WEEK]
        month, year = self._levels[Period.MONTH], self._levels[Period.YEAR]

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
        direction = trade_direction(day.cpr, week.cpr, session.open)
        zones = detect_hot_zones(
            day,
            week,
            month,
            year,
            self.parameters.hot_zone_tolerance,
            self.parameters.hot_zone_min_score,
        )
        h4_break, l4_break = hot_zone_breakouts(
            zones, day.camarilla.h4, day.camarilla.l4, bar.close, self._previous_close
        )

        action, codes, entry = self._decide(bar, signals)
        context = _clean(
            {
                "session_open": session.open,
                "session_open_source": session.open_source,
                "cpr_daily": day.cpr.to_dict(),
                "cpr_weekly": week.cpr.to_dict(),
                "camarilla_daily": day.camarilla.to_dict(),
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
                "trade_direction": direction.to_dict(),
                "hot_zones": {
                    "zones": [zone.to_dict() for zone in zones],
                    "h4_breakout": h4_break,
                    "l4_breakdown": l4_break,
                },
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

    def _zones(self) -> list[Zone]:
        names = {Period.DAY: "daily_mtz", Period.WEEK: "weekly_mtz"}
        zones = []
        for period in self.parameters.mtz_periods:
            cpr = self._levels[period].cpr
            if not is_na(cpr.tc) and not is_na(cpr.bc):
                zones.append(Zone(names[period], cpr.tc, cpr.bc))
        return zones

    def _decide(
        self, bar: Bar, signals: list[ReversalSignal]
    ) -> tuple[DecisionAction, list[str], EntrySignal | None]:
        zones = self._zones()
        if not zones:
            return DecisionAction.HOLD, ["NO_MTZ_LEVELS"], None
        if not signals:
            return DecisionAction.HOLD, ["NO_REVERSAL_SIGNAL"], None

        # Proximity is tested on the bar before the confirming bar, as the script's labels do.
        reference = self._previous_bar
        touched = [zone for zone in zones if reference is not None and zone.touched_by(reference)]
        if not touched:
            return DecisionAction.HOLD, ["REVERSAL_NOT_AT_MTZ", *_pattern_codes(signals)], None

        sides = {signal.is_long for signal in signals}
        if len(sides) > 1:
            return DecisionAction.HOLD, ["CONFLICTING_SIGNALS", *_pattern_codes(signals)], None
        is_long = sides.pop()

        # With several patterns on one bar, the widest signal candle sets the stop.
        if is_long:
            stop = min(signal.signal_bar.low for signal in signals)
            candidates = [z for z in zones if z not in touched and z.bottom > bar.close]
            target_zone = min(candidates, key=lambda z: z.bottom, default=None)
            target = target_zone.bottom if target_zone else math.nan
            stop_valid = stop < bar.close
        else:
            stop = max(signal.signal_bar.high for signal in signals)
            candidates = [z for z in zones if z not in touched and z.top < bar.close]
            target_zone = max(candidates, key=lambda z: z.top, default=None)
            target = target_zone.top if target_zone else math.nan
            stop_valid = stop > bar.close

        codes = [*_pattern_codes(signals), *(f"AT_{z.name.upper()}" for z in touched)]
        if target_zone is None:
            return DecisionAction.HOLD, ["NO_TARGET_ZONE", *codes], None
        if not stop_valid:
            return DecisionAction.HOLD, ["INVALID_STOP", *codes], None

        entry = EntrySignal(
            side="long" if is_long else "short",
            patterns=sorted({signal.code for signal in signals}),
            touched_zones=[zone.name for zone in touched],
            signal_candle_high=max(signal.signal_bar.high for signal in signals),
            signal_candle_low=min(signal.signal_bar.low for signal in signals),
            stop_loss=stop,
            target=target,
            target_zone=target_zone.name,
        )
        action = DecisionAction.BUY if is_long else DecisionAction.SELL
        return action, [*codes, f"TARGET_{target_zone.name.upper()}"], entry


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
