"""Multi-timeframe hot zones (strategy.pine 205-206, 507-560, 1177-1196). Context only."""

import math
from dataclasses import asdict, dataclass
from typing import Any

from app.strategy.periods import PeriodLevels


@dataclass(frozen=True)
class HotZone:
    price: float
    score: int
    level: str
    is_bull: bool
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_near(a: float, b: float, tolerance: float) -> bool:
    return (
        not math.isnan(a)
        and not math.isnan(b)
        and abs(a - b) / ((a + b) / 2.0) * 100.0 <= tolerance
    )


def _score(day: float, week: float, month: float, year: float, tolerance: float) -> int:
    swing = is_near(day, week, tolerance)
    investor = is_near(day, month, tolerance) or is_near(day, year, tolerance)
    return 1 + int(swing) + int(investor)


def detect_hot_zones(
    day: PeriodLevels,
    week: PeriodLevels,
    month: PeriodLevels,
    year: PeriodLevels,
    tolerance: float,
    min_score: int,
) -> list[HotZone]:
    groups: list[tuple[list[Any], list[tuple[str, str, bool]]]] = [
        (
            [lv.cpr for lv in (day, week, month, year)],
            [
                ("pp", "PP", True),
                ("tc", "TC", True),
                ("bc", "BC", False),
                ("r1", "R1", True),
                ("s1", "S1", False),
            ],
        ),
        (
            [lv.camarilla for lv in (day, week, month, year)],
            [
                ("h3", "CAM-H3", True),
                ("l3", "CAM-L3", False),
                ("h4", "CAM-H4", True),
                ("l4", "CAM-L4", False),
            ],
        ),
    ]
    zones = []
    for levels, fields in groups:
        for attr, name, is_bull in fields:
            d, w, m, y = (getattr(level, attr) for level in levels)
            score = _score(d, w, m, y, tolerance)
            if score >= min_score and not math.isnan(d):
                description = (
                    f"{name}: Day"
                    + ("+Week" if is_near(d, w, tolerance) else "")
                    + ("+Month" if is_near(d, m, tolerance) else "")
                    + ("+Year" if is_near(d, y, tolerance) else "")
                )
                zones.append(HotZone(d, score, name, is_bull, description))
    return zones


def hot_zone_breakouts(
    zones: list[HotZone], h4: float, l4: float, close: float, previous_close: float
) -> tuple[bool, bool]:
    """H4 breakout up and L4 breakdown, each only when that level sits in a hot zone."""
    h4_in_zone = any(is_near(zone.price, h4, 0.5) for zone in zones)
    l4_in_zone = any(is_near(zone.price, l4, 0.5) for zone in zones)
    up = close > h4 and previous_close <= h4 and h4_in_zone
    down = close < l4 and previous_close >= l4 and l4_in_zone
    return up, down
