"""Hot zone scalp (strategy4.txt) on hand-built candles (test data only, not market prices).

The daily candles are those of test_strategy_engine.py. With Friday's close at 102, Monday's
only zone at the default 0.25% tolerance is MTF+ H5 (day H5 112.74 near the week's BC 112.5):
bullish, score 2. Month and year levels need history the fixture lacks.
"""

import dataclasses
import math

import pytest

from app.domain.enums import DecisionAction
from app.strategy.hot_zone_scalp import detect_zones
from app.strategy.levels import PeriodBar, calculate_camarilla, calculate_cpr
from app.strategy.parameters import StrategyOptions, StrategyParameters
from app.strategy.periods import Period
from app.strategy.runner import evaluate
from tests.unit.test_strategy_engine import LONG_AT_DAILY_MTZ, daily_frame, intraday_frame


def scalp(**options) -> StrategyParameters:
    return StrategyOptions(strategy="hot_zone", **options).apply(StrategyParameters())


def test_reversal_toward_the_nearest_zone_targets_the_next_level() -> None:
    decision = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily_frame(), scalp())[2]
    nearest = decision.context["hot_zone_scalp"]["nearest"]
    assert (nearest["name"], nearest["is_bull"]) == ("MTF+ H5", True)
    assert decision.action == DecisionAction.BUY
    assert decision.reason_codes == ["HZ_MTF_LONG", "TRIGGER_OR", "TARGET_H3", "EXIT_FIXED_TARGET"]
    assert decision.signal is not None
    assert decision.signal.stop_loss == 100.0  # the signal candle's low
    assert decision.signal.target == pytest.approx(104.75)  # H3, the next level above 101.5


def test_the_zone_counts_however_far_away_as_the_script_does() -> None:
    # The close (101.5) is more than 10% below the zone (112.74), and the trade is still taken.
    decision = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily_frame(), scalp())[2]
    assert decision.action == DecisionAction.BUY


def test_a_reversal_against_the_zone_direction_is_not_taken() -> None:
    bars = [
        (101.0, 101.2, 100.8, 101.0),
        (101.1, 101.3, 100.5, 100.6),
        (100.6, 100.7, 100.3, 100.4),  # confirms an outside reversal short
    ]
    decision = evaluate(intraday_frame(bars), daily_frame(), scalp())[2]
    assert decision.reason_codes == ["SIGNAL_AGAINST_ZONE"]


def test_unchosen_zone_types_are_ignored() -> None:
    decision = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily_frame(), scalp(hz_types=("GPZ",)))[
        2
    ]
    assert decision.reason_codes == ["NO_HOT_ZONE"]


def test_the_panel_gate_needs_the_panels_own_permission() -> None:
    # Friday close 100.3: the trade direction panel allows neither side on Monday.
    frame = daily_frame(friday_close=100.3)
    gated = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), frame, scalp(hz_panel_gate=True))[2]
    assert gated.context["hot_zone_scalp"]["panel_allow_long"] is False
    assert gated.reason_codes == ["PANEL_BLOCKS_DIRECTION"]
    ungated = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), frame, scalp())[2]
    assert ungated.action == DecisionAction.BUY


def levels():
    nan = math.nan
    bar = PeriodBar(104, 105, 95, 102)
    return calculate_cpr(bar, 100.5, nan, nan), calculate_camarilla(bar, 100.5, nan, nan)


def empty():
    nan = math.nan
    return calculate_cpr(None, nan, nan, nan), calculate_camarilla(None, nan, nan, nan)


def test_pooled_confluence_scores_and_merges_nearby_zones() -> None:
    (cpr, cam), (no_cpr, no_cam) = levels(), empty()
    cprs = {Period.DAY: cpr, Period.WEEK: cpr, Period.MONTH: no_cpr, Period.YEAR: no_cpr}
    cams = {Period.DAY: cam, Period.WEEK: cam, Period.MONTH: no_cam, Period.YEAR: no_cam}
    zones = [z for z in detect_zones(cprs, cams, 0.25, 2) if z.kind == "MTF"]
    # Each of the 13 day levels meets itself on the week (score 2); L4 (96.5) lies within 0.25%
    # of S1 (96.33), so it merges into the S1 zone found first.
    assert len(zones) == 12
    assert all(z.score == 2 for z in zones)
    assert "MTF+ L4" not in {z.name for z in zones}
    assert detect_zones(cprs, cams, 0.25, 3) == []


def test_golden_pivot_zone_is_cpr_near_camarilla_h3_or_l3() -> None:
    (cpr, cam), (no_cpr, no_cam) = levels(), empty()
    cam = dataclasses.replace(cam, h3=cpr.tc + 0.1)
    cprs = {Period.DAY: cpr, Period.WEEK: no_cpr, Period.MONTH: no_cpr, Period.YEAR: no_cpr}
    cams = {Period.DAY: cam, Period.WEEK: no_cam, Period.MONTH: no_cam, Period.YEAR: no_cam}
    [gpz] = [z for z in detect_zones(cprs, cams, 0.25, 2) if z.kind == "GPZ"]
    assert gpz.name == "GPZ TC/H3"
    assert gpz.is_bull
    assert gpz.price == pytest.approx(cpr.tc + 0.05)
    assert gpz.score == 3


def test_zone_options_validate() -> None:
    assert StrategyOptions(hz_types=("GPZ", "MTF")).hz_types == ("MTF", "GPZ")
    with pytest.raises(ValueError, match="at least one"):
        StrategyOptions(hz_types=())
    with pytest.raises(ValueError, match="Unknown"):
        StrategyOptions(hz_types=("XX",))
    with pytest.raises(ValueError):
        StrategyOptions(hz_min_score=5)
