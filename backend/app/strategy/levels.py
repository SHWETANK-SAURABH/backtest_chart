"""CPR and Camarilla levels: f_calculateCPR and f_calculateCamarilla (strategy.pine 338-500).

Operation order follows the Pine source exactly, so floating-point results match.
"""

from dataclasses import asdict, dataclass
from typing import Any

from app.strategy.pine import NA

HIST_TRENDING = "Trending"
HIST_POSSIBLE = "Possible Trending"
HIST_SIDEWAYS = "Sideways"
HIST_SIDEWAYS_TRADE = "Sideways Trading"


@dataclass(frozen=True)
class PeriodBar:
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Relationship:
    """How a period's band sits relative to the previous period's band."""

    bullish: bool
    bearish: bool
    overlap_bullish: bool
    overlap_bearish: bool
    inside: bool
    outside: bool

    @property
    def name(self) -> str:
        # Same precedence as f_trendColorIdx.
        for flag, label in (
            (self.bullish, "higher"),
            (self.bearish, "lower"),
            (self.overlap_bullish, "higher_overlapping"),
            (self.overlap_bearish, "lower_overlapping"),
            (self.inside, "inside"),
            (self.outside, "outside"),
        ):
            if flag:
                return label
        return "unchanged"


@dataclass(frozen=True)
class CprLevels:
    pp: float
    tc: float
    bc: float
    r1: float
    r2: float
    r3: float
    r4: float
    s1: float
    s2: float
    s3: float
    s4: float
    ph: float
    pl: float
    width_percent: float
    histogram: str
    relationship: str
    bias: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CamarillaLevels:
    center: float
    h1: float
    h2: float
    h3: float
    h4: float
    h5: float
    h6: float
    l1: float
    l2: float
    l3: float
    l4: float
    l5: float
    l6: float
    relationship: str
    bias: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _raw_cpr(high: float, low: float, close: float) -> tuple[float, ...]:
    pp = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = pp - bc + pp
    r1 = 2 * pp - low
    s1 = 2 * pp - high
    r2 = pp + high - low
    s2 = pp - (high - low)
    r3 = high + 2 * (pp - low)
    s3 = low - 2 * (high - pp)
    r4 = r3 + r2 - r1
    s4 = s3 + s2 - s1
    if tc < bc:
        tc, bc = bc, tc
    return pp, tc, bc, r1, r2, r3, r4, s1, s2, s3, s4


def cpr_band(previous: PeriodBar | None) -> tuple[float, float]:
    """TC and BC computed from a period's prior bar, or NaN when there is no prior bar."""
    if previous is None:
        return NA, NA
    _, tc, bc, *_ = _raw_cpr(previous.high, previous.low, previous.close)
    return tc, bc


def histogram(width_percent: float) -> str:
    if width_percent < 0.25:
        return HIST_TRENDING
    if width_percent < 0.50:
        return HIST_POSSIBLE
    if width_percent < 0.75:
        return HIST_SIDEWAYS
    return HIST_SIDEWAYS_TRADE


def calculate_cpr(
    previous: PeriodBar | None, session_open: float, prev_tc: float, prev_bc: float
) -> CprLevels:
    """Levels for a period from its previous bar. prev_tc and prev_bc are the previous period's."""
    if previous is None:
        values: tuple[float, ...] = (NA,) * 11
        ph = pl = NA
    else:
        values = _raw_cpr(previous.high, previous.low, previous.close)
        ph, pl = previous.high, previous.low
    pp, tc, bc, r1, r2, r3, r4, s1, s2, s3, s4 = values

    rel = Relationship(
        bullish=bc > prev_tc,
        overlap_bullish=(bc < prev_tc and bc > prev_bc) and tc > prev_tc,
        bearish=tc < prev_bc,
        overlap_bearish=(tc > prev_bc and tc < prev_tc) and (bc < prev_bc),
        inside=tc < prev_tc and bc > prev_bc,
        outside=tc > prev_tc and bc < prev_bc,
    )

    bias = "Trend Rejected"
    if rel.bullish or rel.overlap_bullish:
        bias = "Bull Accept" if session_open > bc else "Sell here"
    elif rel.bearish or rel.overlap_bearish:
        bias = "Bear Accept" if session_open < tc else "Buy here"
    elif rel.inside:
        if session_open > r1:
            bias = "Bullish Breakout"
        elif session_open < s1:
            bias = "Bearish Breakout"
        else:
            bias = "Inside - No Setup"
    elif rel.outside:
        bias = "Outside - Target CPR"

    width = abs(tc - bc) / pp * 100
    return CprLevels(
        pp, tc, bc, r1, r2, r3, r4, s1, s2, s3, s4, ph, pl,
        width_percent=width,
        histogram=histogram(width),
        relationship=rel.name,
        bias=bias,
    )  # fmt: skip


def _raw_camarilla(high: float, low: float, close: float) -> tuple[float, ...]:
    r = high - low
    h1 = close + r * (1.1 / 12)
    h2 = close + r * (1.1 / 6)
    h3 = close + r * (1.1 / 4)
    h4 = close + r * (1.1 / 2)
    h5 = high / low * close
    h6 = h5 + 1.168 * (h5 - h4)
    l1 = close - r * (1.1 / 12)
    l2 = close - r * (1.1 / 6)
    l3 = close - r * (1.1 / 4)
    l4 = close - r * (1.1 / 2)
    l5 = close - (h5 - close)
    l6 = close - (h6 - close)
    return close, h1, h2, h3, h4, h5, h6, l1, l2, l3, l4, l5, l6


def camarilla_h3_l3(previous: PeriodBar | None) -> tuple[float, float]:
    if previous is None:
        return NA, NA
    values = _raw_camarilla(previous.high, previous.low, previous.close)
    return values[3], values[9]


def calculate_camarilla(
    previous: PeriodBar | None, session_open: float, prev_h3: float, prev_l3: float
) -> CamarillaLevels:
    if previous is None:
        values: tuple[float, ...] = (NA,) * 13
    else:
        values = _raw_camarilla(previous.high, previous.low, previous.close)
    center, h1, h2, h3, h4, h5, h6, l1, l2, l3, l4, l5, l6 = values

    rel = Relationship(
        bullish=l3 > prev_h3,
        overlap_bullish=l3 < prev_h3 and l3 > prev_l3 and h3 > prev_h3,
        bearish=h3 < prev_l3,
        overlap_bearish=h3 > prev_l3 and h3 < prev_h3 and l3 < prev_l3,
        inside=h3 < prev_h3 and l3 > prev_l3,
        outside=h3 > prev_h3 and l3 < prev_l3,
    )

    bias = "Trend Rejected"
    if rel.bullish or rel.overlap_bullish:
        bias = "Bull Accept" if session_open > l3 else "Sell here"
    elif rel.bearish or rel.overlap_bearish:
        bias = "Bear Accept" if session_open < h3 else "Buy here"
    elif rel.inside:
        if session_open > h4:
            bias = "Bullish Breakout"
        elif session_open < l4:
            bias = "Bearish Breakout"
        else:
            bias = "Inside - No Setup"
    elif rel.outside:
        bias = "Outside - Target Center"

    return CamarillaLevels(
        center, h1, h2, h3, h4, h5, h6, l1, l2, l3, l4, l5, l6,
        relationship=rel.name,
        bias=bias,
    )  # fmt: skip
