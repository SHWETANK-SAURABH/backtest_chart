"""Hot zone scalp: the hot zones and zone trade of prompt/strategy4.txt, a backtest choice.

strategy4.txt rebuilds the hot zones (f_detectHotZones, lines 555-769) and lets the trade
direction panel offer a scalp toward the nearest zone, confirmed by a WR/DR/OR/ER candle
(lines 1022-1041, 1221-1309). The owner chose on 2026-11-04:
- "At a zone" as the script is written: the nearest of the day's zones to the close sets the
  direction, however far away it is.
- Zone types are options; MTF confluence and Golden Pivot Zones are the defaults.
- Exit at the next pivot level beyond the close, stop at the signal candle.
- An option requires the trade direction panel's own permission (structure, gap or PDH/PDL).
Other choices are listed in docs/hot-zone-scalp.md.

Levels, reversal candles and the candle context come from the MTZ strategy; only the entry
decision differs. The chart timeframe is daily, so Day is the anchor and Week, Month and Year are
the higher timeframes.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.domain.enums import DecisionAction
from app.strategy.engine import EntrySignal, MtzReversalStrategy, SessionInfo
from app.strategy.hot_zones import is_near
from app.strategy.levels import CamarillaLevels, CprLevels
from app.strategy.periods import Period
from app.strategy.reversal import Bar, ReversalSignal
from app.strategy.trade_direction import trade_direction

ZONE_TYPES = ("MTF", "GPZ", "DPZ", "MTF_STAR", "PP_CC")
NAMED_SCORE = 3


@dataclass(frozen=True)
class Zone:
    price: float
    score: int
    kind: str  # one of ZONE_TYPES
    name: str
    is_bull: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": self.price,
            "score": self.score,
            "kind": self.kind,
            "name": self.name,
            "is_bull": self.is_bull,
        }


def _pool(cpr: CprLevels, cam: CamarillaLevels) -> list[float]:
    return [
        cpr.pp, cpr.tc, cpr.bc, cpr.r1, cpr.r2, cpr.s1, cpr.s2,
        cam.h3, cam.h4, cam.h5, cam.l3, cam.l4, cam.l5,
    ]  # fmt: skip


ANCHOR_NAMES = ("PP", "TC", "BC", "R1", "R2", "S1", "S2", "H3", "H4", "H5", "L3", "L4", "L5")
ANCHOR_BULLS = (True, True, False, True, True, False, False, True, True, True, False, False, False)


def detect_zones(
    cprs: dict[Period, CprLevels],
    cams: dict[Period, CamarillaLevels],
    tolerance: float,
    min_score: int,
) -> list[Zone]:
    """f_detectHotZones of strategy4.txt with the daily chart as the anchor."""
    day, week, month, year = Period.DAY, Period.WEEK, Period.MONTH, Period.YEAR
    others = [_pool(cprs[p], cams[p]) for p in (week, month, year)]
    zones: list[Zone] = []

    # Pooled MTF confluence: 1 for the day, +1 for each other timeframe with any pooled level near.
    pooled: list[Zone] = []
    for value, name, bull in zip(
        _pool(cprs[day], cams[day]), ANCHOR_NAMES, ANCHOR_BULLS, strict=True
    ):
        if math.isnan(value):
            continue
        score = 1 + sum(any(is_near(value, v, tolerance) for v in pool) for pool in others)
        if score < min_score:
            continue
        zone = Zone(value, score, "MTF", f"MTF+ {name}", bull)
        near = next((i for i, z in enumerate(pooled) if is_near(z.price, value, tolerance)), None)
        if near is None:
            pooled.append(zone)
        elif score > pooled[near].score:
            pooled[near] = zone
    zones.extend(pooled)

    # Named setups, each scored 3, on the day and the next two higher timeframes.
    for period in (day, week, month):
        cpr, cam = cprs[period], cams[period]
        for level, label in ((cpr.tc, "TC"), (cpr.bc, "BC"), (cpr.pp, "PP")):
            if is_near(level, cam.h3, tolerance):
                zones.append(
                    Zone((level + cam.h3) / 2, NAMED_SCORE, "GPZ", f"GPZ {label}/H3", True)
                )
            if is_near(level, cam.l3, tolerance):
                zones.append(
                    Zone((level + cam.l3) / 2, NAMED_SCORE, "GPZ", f"GPZ {label}/L3", False)
                )
        if is_near(cpr.r2, cam.h4, tolerance):
            zones.append(Zone((cpr.r2 + cam.h4) / 2, NAMED_SCORE, "DPZ", "DPZ R2/H4", True))
        if is_near(cpr.s2, cam.l4, tolerance):
            zones.append(Zone((cpr.s2 + cam.l4) / 2, NAMED_SCORE, "DPZ", "DPZ S2/L4", False))

    # MTF star: the day's R1 (S1) near the week's or the top timeframe's PP/TC (PP/BC).
    top = next((cprs[p] for p in (year, month, week) if not math.isnan(cprs[p].pp)), cprs[week])
    d = cprs[day]
    for compare in (cprs[week].pp, cprs[week].tc, top.pp, top.tc):
        if is_near(d.r1, compare, tolerance):
            zones.append(Zone(d.r1, NAMED_SCORE, "MTF_STAR", "MTF★ R1", True))
    for compare in (cprs[week].pp, cprs[week].bc, top.pp, top.bc):
        if is_near(d.s1, compare, tolerance):
            zones.append(Zone(d.s1, NAMED_SCORE, "MTF_STAR", "MTF★ S1", False))

    # PP/CC: a timeframe's pivot near its Camarilla centre (always marked bullish in the script).
    for period in (day, week, month, year):
        pp, center = cprs[period].pp, cams[period].center
        if is_near(pp, center, tolerance):
            zones.append(Zone((pp + center) / 2, NAMED_SCORE, "PP_CC", "PP/CC", True))
    return zones


class HotZoneScalpStrategy(MtzReversalStrategy):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._scalp_zones: list[Zone] = []
        self._panel_long = True
        self._panel_short = True
        self._nearest: Zone | None = None

    def start_session(self, session: SessionInfo) -> None:
        super().start_session(session)
        levels = self._levels
        chosen = set(self.parameters.hz_types)
        self._scalp_zones = [
            z
            for z in detect_zones(
                {p: levels[p].cpr for p in Period},
                {p: levels[p].camarilla for p in Period},
                self.parameters.hot_zone_tolerance,
                self.parameters.hz_min_score,
            )
            if z.kind in chosen
        ]
        # The panel's own permission, without the zone's: structure, gap or PDH/PDL.
        panel = trade_direction(levels[Period.DAY].cpr, levels[Period.WEEK].cpr, session.open)
        self._panel_long, self._panel_short = panel.allow_long, panel.allow_short

    def _extra_context(self) -> dict[str, Any]:
        return {
            "hot_zone_scalp": {
                "zones": [z.to_dict() for z in self._scalp_zones],
                "nearest": self._nearest.to_dict() if self._nearest else None,
                "panel_allow_long": self._panel_long,
                "panel_allow_short": self._panel_short,
            }
        }

    def _entry(
        self, timestamp: datetime, bar: Bar, signals: list[ReversalSignal]
    ) -> tuple[DecisionAction, list[str], EntrySignal | None]:
        # As strategy4.txt: the zone nearest the close, however far, sets the direction.
        self._nearest = min(self._scalp_zones, key=lambda z: abs(bar.close - z.price), default=None)
        zone = self._nearest
        if zone is None:
            return DecisionAction.HOLD, ["NO_HOT_ZONE"], None
        if not signals:
            return DecisionAction.HOLD, ["NO_REVERSAL_SIGNAL"], None
        matching = [s for s in signals if s.is_long == zone.is_bull]
        if not matching:
            return DecisionAction.HOLD, ["SIGNAL_AGAINST_ZONE"], None
        is_long = zone.is_bull
        if self.parameters.hz_panel_gate and not (
            self._panel_long if is_long else self._panel_short
        ):
            return DecisionAction.HOLD, ["PANEL_BLOCKS_DIRECTION"], None

        name, target = self._next_level(bar.close, is_long)
        triggers = sorted({s.code for s in matching})
        if is_long:
            stop = min(s.signal_bar.low for s in matching)
            stop_valid = stop < bar.close
        else:
            stop = max(s.signal_bar.high for s in matching)
            stop_valid = stop > bar.close
        if target is None:
            return DecisionAction.HOLD, ["NO_TARGET_LEVEL"], None
        if not stop_valid:
            return DecisionAction.HOLD, ["INVALID_STOP"], None

        setup = f"HZ_{zone.kind}"
        entry = EntrySignal(
            side="long" if is_long else "short",
            patterns=[setup],
            touched_zones=[zone.name],
            signal_candle_high=max(s.signal_bar.high for s in matching),
            signal_candle_low=min(s.signal_bar.low for s in matching),
            stop_loss=stop,
            target=target,
            target_zone=name,
            exit_mode="EXIT_FIXED_TARGET",
        )
        codes = [
            f"{setup}_{'LONG' if is_long else 'SHORT'}",
            *(f"TRIGGER_{t}" for t in triggers),
            f"TARGET_{name.upper()}",
            "EXIT_FIXED_TARGET",
        ]
        return (DecisionAction.BUY if is_long else DecisionAction.SELL), codes, entry

    def _next_level(self, price: float, is_long: bool) -> tuple[str, float | None]:
        """The nearest daily CPR or Camarilla (H3-H6, L3-L6) level beyond the price."""
        day = self._levels[Period.DAY]
        cpr, cam = day.cpr, day.camarilla
        levels = {
            "pp": cpr.pp, "tc": cpr.tc, "bc": cpr.bc,
            "r1": cpr.r1, "r2": cpr.r2, "r3": cpr.r3, "r4": cpr.r4,
            "s1": cpr.s1, "s2": cpr.s2, "s3": cpr.s3, "s4": cpr.s4,
            "h3": cam.h3, "h4": cam.h4, "h5": cam.h5, "h6": cam.h6,
            "l3": cam.l3, "l4": cam.l4, "l5": cam.l5, "l6": cam.l6,
        }  # fmt: skip
        beyond = [
            (name, value)
            for name, value in levels.items()
            if not math.isnan(value) and (value > price if is_long else value < price)
        ]
        if not beyond:
            return "", None
        name, value = (min if is_long else max)(beyond, key=lambda item: item[1])
        return name, value
