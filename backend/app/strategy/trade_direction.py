"""Trade direction panel: f_trade_direction and f_resolveMarketState (strategy.pine 681-909).

Ported for context and reporting. The owner confirmed on 2026-11-02 that entries do not depend on
these permissions.
"""

from dataclasses import asdict, dataclass
from typing import Any

from app.strategy.levels import (
    HIST_POSSIBLE,
    HIST_SIDEWAYS,
    HIST_SIDEWAYS_TRADE,
    HIST_TRENDING,
    CprLevels,
)

BIAS_BULL = "BULL"
BIAS_BEAR = "BEAR"
BIAS_NEUTRAL = "NEUTRAL"

LOC_ABOVE_BOTH = "ABOVE_BOTH"
LOC_BELOW_BOTH = "BELOW_BOTH"
LOC_INSIDE_BOTH = "INSIDE_BOTH"
LOC_BETWEEN = "BETWEEN"

MS_STRONG_BULL = "STRONG_BULL_TREND"
MS_STRONG_BEAR = "STRONG_BEAR_TREND"
MS_BULL_CONT = "BULL_CONTINUATION"
MS_BEAR_CONT = "BEAR_CONTINUATION"
MS_BULL_PULLBACK = "BULLISH_PULLBACK"
MS_BEAR_PULLBACK = "BEARISH_PULLBACK"
MS_BULL_COMP = "BULLISH_COMPRESSION"
MS_BEAR_COMP = "BEARISH_COMPRESSION"
MS_NEUTRAL_COMP = "NEUTRAL_COMPRESSION"
MS_SIDEWAYS = "SIDEWAYS_BALANCE"
MS_BULL_TRAP = "BULL_TRAP_RISK"
MS_BEAR_TRAP = "BEAR_TRAP_RISK"
MS_TRANSITION = "TRANSITION_PULLBACK"
MS_SHORT_BREAKDOWN = "SHORT_TERM_BREAKDOWN"
MS_SHORT_COVERING = "SHORT_COVERING_RISK"
MS_BEAR_FAILURE = "BEARISH_FAILURE"
MS_BULL_FAILURE = "BULLISH_FAILURE"

AGG_FULL = "FULL"
AGG_RED = "REDUCED"
AGG_SCALP = "SCALP_ONLY"
AGG_NONE = "NONE"


@dataclass(frozen=True)
class TradeDirection:
    trade_bias: str
    direction_bias: str
    price_location: str
    market_state: str
    histogram: str
    table_tennis: bool
    final_allow_long: bool
    final_allow_short: bool
    gap_allow_long: bool
    gap_allow_short: bool
    pdhl_allow_long: bool
    pdhl_allow_short: bool
    allow_long: bool
    allow_short: bool
    aggression: str
    open_inside_mtz: bool
    virgin_cpr: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def map_bias(bias: str) -> str:
    if bias in ("Bull Accept", "Bullish Breakout", "Buy here"):
        return BIAS_BULL
    if bias in ("Bear Accept", "Bearish Breakout", "Sell here"):
        return BIAS_BEAR
    return BIAS_NEUTRAL


def resolve_market_state(
    bias_2d: str, bias_2w: str, location: str, bear_fail: bool, bull_fail: bool
) -> str:
    if bear_fail:
        return MS_BEAR_FAILURE
    if bull_fail:
        return MS_BULL_FAILURE
    if bias_2d == BIAS_BULL and bias_2w == BIAS_BULL:
        return {
            LOC_ABOVE_BOTH: MS_STRONG_BULL,
            LOC_INSIDE_BOTH: MS_BULL_COMP,
            LOC_BETWEEN: MS_BULL_PULLBACK,
        }.get(location, MS_BULL_TRAP)
    if bias_2d == BIAS_BEAR and bias_2w == BIAS_BEAR:
        return {
            LOC_BELOW_BOTH: MS_STRONG_BEAR,
            LOC_INSIDE_BOTH: MS_BEAR_COMP,
            LOC_BETWEEN: MS_BEAR_PULLBACK,
        }.get(location, MS_BEAR_TRAP)
    if bias_2d == BIAS_BEAR and bias_2w == BIAS_BULL:
        return {
            LOC_ABOVE_BOTH: MS_BULL_CONT,
            LOC_INSIDE_BOTH: MS_NEUTRAL_COMP,
            LOC_BETWEEN: MS_TRANSITION,
        }.get(location, MS_SHORT_BREAKDOWN)
    if bias_2d == BIAS_BULL and bias_2w == BIAS_BEAR:
        return {
            LOC_BELOW_BOTH: MS_BEAR_CONT,
            LOC_INSIDE_BOTH: MS_NEUTRAL_COMP,
            LOC_BETWEEN: MS_TRANSITION,
        }.get(location, MS_SHORT_COVERING)
    return MS_SIDEWAYS


def trade_direction(trade: CprLevels, direction: CprLevels, session_open: float) -> TradeDirection:
    bias_2d = map_bias(trade.bias)
    bias_2w = map_bias(direction.bias)

    above_2d = session_open > trade.tc
    below_2d = session_open < trade.bc
    inside_2d = not above_2d and not below_2d
    above_2w = session_open > direction.tc
    below_2w = session_open < direction.bc
    inside_2w = not above_2w and not below_2w

    if above_2d and above_2w:
        location = LOC_ABOVE_BOTH
    elif below_2d and below_2w:
        location = LOC_BELOW_BOTH
    elif inside_2d and inside_2w:
        location = LOC_INSIDE_BOTH
    else:
        location = LOC_BETWEEN

    bear_fail = bias_2d == BIAS_BULL and bias_2w == BIAS_BEAR and location == LOC_BELOW_BOTH
    bull_fail = bias_2d == BIAS_BEAR and bias_2w == BIAS_BULL and location == LOC_ABOVE_BOTH
    state = resolve_market_state(bias_2d, bias_2w, location, bear_fail, bull_fail)
    hist = trade.histogram

    base_long = state in (
        MS_STRONG_BULL,
        MS_BULL_CONT,
        MS_BULL_PULLBACK,
        MS_SHORT_COVERING,
        MS_BULL_COMP,
    )
    base_short = state in (
        MS_STRONG_BEAR,
        MS_BEAR_CONT,
        MS_BEAR_PULLBACK,
        MS_SHORT_BREAKDOWN,
        MS_BEAR_COMP,
    )
    if hist == HIST_TRENDING:
        base_aggression = AGG_FULL
    elif hist == HIST_POSSIBLE:
        base_aggression = AGG_RED
    elif hist == HIST_SIDEWAYS_TRADE:
        base_aggression = AGG_SCALP
    else:
        base_aggression = AGG_NONE

    sideways_state = state in (MS_NEUTRAL_COMP, MS_SIDEWAYS)
    table_tennis = sideways_state and hist == HIST_SIDEWAYS_TRADE

    if state == MS_BEAR_FAILURE:
        base_long, base_short = False, True
    if state == MS_BULL_FAILURE:
        base_long, base_short = True, False

    blocked = hist == HIST_SIDEWAYS or (hist == HIST_SIDEWAYS_TRADE and not sideways_state)
    final_long = table_tennis or (base_long and not blocked)
    final_short = table_tennis or (base_short and not blocked)

    open_above_r1 = session_open > trade.r1
    open_below_s1 = session_open < trade.s1
    open_above_pdh = session_open > trade.ph
    open_below_pdl = session_open < trade.pl

    gap_long = open_above_r1 and not open_below_s1
    gap_short = open_below_s1 and not open_above_r1
    pdhl_long = open_above_pdh and not open_below_pdl
    pdhl_short = open_below_pdl and not open_above_pdh

    allow_long = final_long or gap_long or pdhl_long
    allow_short = final_short or gap_short or pdhl_short

    if not allow_long and not allow_short:
        aggression = AGG_NONE
    elif not final_long and not final_short:
        aggression = AGG_SCALP
    else:
        aggression = base_aggression

    return TradeDirection(
        trade_bias=bias_2d,
        direction_bias=bias_2w,
        price_location=location,
        market_state=state,
        histogram=hist,
        table_tennis=table_tennis,
        final_allow_long=final_long,
        final_allow_short=final_short,
        gap_allow_long=gap_long,
        gap_allow_short=gap_short,
        pdhl_allow_long=pdhl_long,
        pdhl_allow_short=pdhl_short,
        allow_long=allow_long,
        allow_short=allow_short,
        aggression=aggression,
        open_inside_mtz=session_open >= trade.bc and session_open <= trade.tc,
        virgin_cpr=trade.ph < trade.bc or trade.pl > trade.tc,
    )
