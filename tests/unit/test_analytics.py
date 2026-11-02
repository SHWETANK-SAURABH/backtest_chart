"""Performance calculations against hand-worked values (test trades, not market results)."""

import math
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest

from app.analytics import regimes
from app.analytics.metrics import (
    PeriodPerformance,
    daily_performance,
    equity_curve,
    max_drawdown,
    monthly_performance,
    sharpe_ratio,
    trade_statistics,
    unit_summary,
)
from app.domain.candle import EXCHANGE_TZ


@dataclass(frozen=True)
class T:
    net_points: float
    trading_date: date = date(2025, 6, 16)
    holding_seconds: int = 600
    entry_price: float = 20000.0
    exit_time: datetime = datetime(2025, 6, 16, 4, 0, tzinfo=UTC)


def series(results: list[float]) -> list[T]:
    start = datetime(2025, 6, 16, 4, 0, tzinfo=UTC)
    return [T(r, exit_time=start + timedelta(minutes=5 * i)) for i, r in enumerate(results)]


MIXED = series([4, -2, 0, 3, 3, -1])


def test_trade_statistics_match_hand_calculation() -> None:
    s = trade_statistics(MIXED)
    assert (s.total_trades, s.winning_trades, s.losing_trades, s.breakeven_trades) == (6, 3, 2, 1)
    assert s.win_rate == 0.5
    assert s.gross_profit_points == 10
    assert s.gross_loss_points == 3
    assert s.net_points == 7
    assert s.profit_factor == pytest.approx(10 / 3)
    assert s.average_win_points == pytest.approx(10 / 3)
    assert s.average_loss_points == -1.5
    assert s.average_trade_points == pytest.approx(7 / 6)
    assert s.expectancy_points == pytest.approx(7 / 6)
    assert s.average_holding_seconds == 600


def test_breakeven_trades_end_streaks() -> None:
    s = trade_statistics(MIXED)
    assert s.max_consecutive_wins == 2  # the two 3s; the 0 broke the run after 4
    assert s.max_consecutive_losses == 1
    assert trade_statistics(series([-1, -1, -1, 2, -1])).max_consecutive_losses == 3


def test_no_trades_leaves_ratios_undefined() -> None:
    s = trade_statistics([])
    assert s.total_trades == 0
    assert s.win_rate is None
    assert s.profit_factor is None
    assert s.expectancy_points is None
    assert s.average_trade_points is None
    assert s.average_holding_seconds is None
    assert s.net_points == 0


def test_no_losing_trades_leaves_profit_factor_undefined() -> None:
    s = trade_statistics(series([2, 3]))
    assert s.profit_factor is None
    assert s.average_loss_points is None
    assert s.win_rate == 1.0


def test_all_losing_trades() -> None:
    s = trade_statistics(series([-2, -3]))
    assert s.profit_factor == 0.0
    assert s.win_rate == 0.0
    assert s.average_win_points is None
    assert s.expectancy_points == -2.5


def test_equity_curve_and_drawdown() -> None:
    curve = equity_curve(MIXED)
    assert [p.cumulative_points for p in curve] == [4, 2, 2, 5, 8, 7]
    assert [p.drawdown_points for p in curve] == [0, 2, 2, 0, 0, 1]
    assert max_drawdown(curve) == 2


def test_drawdown_counts_losses_from_the_starting_point() -> None:
    assert max_drawdown(equity_curve(series([-3, 1]))) == 3
    assert max_drawdown([]) is None


def test_daily_performance_includes_sessions_without_trades() -> None:
    trades = [T(2, date(2025, 6, 16)), T(-1, date(2025, 6, 16)), T(5, date(2025, 6, 18))]
    sessions = [date(2025, 6, 16), date(2025, 6, 17), date(2025, 6, 18)]
    rows = daily_performance(trades, sessions)
    assert [(r.period, r.trades, r.wins, r.losses, r.net_points) for r in rows] == [
        (date(2025, 6, 16), 2, 1, 1, 1),
        (date(2025, 6, 17), 0, 0, 0, 0),
        (date(2025, 6, 18), 1, 1, 0, 5),
    ]


def test_monthly_performance_sums_sessions() -> None:
    daily = [
        PeriodPerformance(date(2025, 6, 30), 1, 1, 0, 3.0),
        PeriodPerformance(date(2025, 7, 1), 2, 1, 1, -1.0),
        PeriodPerformance(date(2025, 7, 2), 1, 0, 1, -2.0),
    ]
    rows = monthly_performance(daily)
    assert [(r.period, r.trades, r.net_points) for r in rows] == [
        (date(2025, 6, 1), 1, 3.0),
        (date(2025, 7, 1), 3, -3.0),
    ]


def test_sharpe_ratio_on_daily_points() -> None:
    daily = [
        PeriodPerformance(date(2025, 6, d), 1, 0, 0, v) for d, v in ((16, 1), (17, -1), (18, 2))
    ]
    expected = statistics.fmean([1, -1, 2]) / statistics.stdev([1, -1, 2]) * math.sqrt(252)
    assert sharpe_ratio(daily) == pytest.approx(expected)
    assert sharpe_ratio(daily) == pytest.approx(6.928, abs=1e-3)


def test_sharpe_ratio_is_undefined_without_variation_or_history() -> None:
    flat = [PeriodPerformance(date(2025, 6, d), 0, 0, 0, 0.0) for d in (16, 17)]
    assert sharpe_ratio(flat) is None
    assert sharpe_ratio(flat[:1]) is None


def test_unit_summary_separates_points_percent_and_money() -> None:
    summary = unit_summary([T(10.0, entry_price=20000.0), T(-4.0, entry_price=20000.0)])
    assert summary["points"]["net"] == 6
    assert summary["percent_of_index"]["sum_of_trade_returns"] == pytest.approx(0.03)
    assert summary["hypothetical_monetary"]["value"] is None
    assert summary["actual_monetary"]["value"] is None


CONTEXT = {
    "cpr_daily": {"tc": 101.0, "histogram": "Trending", "ph": 110.0, "pl": 100.0},
    "adr": {"value": 20.0, "usage_percent": 40.0},
    "session_open": 101.0,
    "camarilla_daily": {"center": 100.0},
}


def at(hour: int, minute: int, day: int = 16) -> datetime:
    return datetime(2025, 6, day, hour, minute, tzinfo=EXCHANGE_TZ)


def test_regime_labels_from_decision_time_context() -> None:
    result = regimes.labels(CONTEXT, at(9, 30))
    assert result == {
        "trend": "trending",
        "volatility": "low_volatility",  # previous range 10 < 0.65 x ADR 20
        "gap": "gap_up",  # open 1% above the previous close
        "session_part": "opening_hour",
        "hour": "09:00",
        "weekday": "monday",
        "adr_usage": "below_50",
        "cpr_width": "Trending",
    }
    assert regimes.regime(CONTEXT, at(9, 30)) == "trending_low_volatility"


@pytest.mark.parametrize(
    ("moment", "part"),
    [(at(10, 10), "opening_hour"), (at(10, 15), "midday"), (at(13, 30), "afternoon")],
)
def test_session_part_boundaries(moment: datetime, part: str) -> None:
    assert regimes.labels(CONTEXT, moment)["session_part"] == part


@pytest.mark.parametrize(
    ("previous_range", "label"),
    [(12.9, "low_volatility"), (13.0, "normal_volatility"), (26.0, "high_volatility")],
)
def test_volatility_thresholds(previous_range: float, label: str) -> None:
    context = {**CONTEXT, "cpr_daily": {**CONTEXT["cpr_daily"], "ph": 100 + previous_range}}
    assert regimes.labels(context, at(11, 0))["volatility"] == label


def test_missing_context_gives_unknown_labels() -> None:
    result = regimes.labels({}, at(11, 0))
    assert result["trend"] is None
    assert result["volatility"] is None
    assert regimes.regime({}, at(11, 0)) is None


def test_performance_by_condition_groups_trades() -> None:
    grouped = regimes.performance_by_condition(
        [({"trend": "trending"}, 4.0), ({"trend": "trending"}, -2.0), ({"trend": None}, 1.0)],
        [(["OR"], 4.0), (["OR", "WR"], -2.0)],
    )
    assert grouped["trend"]["trending"] == {
        "trades": 2,
        "wins": 1,
        "losses": 1,
        "net_points": 2.0,
        "win_rate": 0.5,
        "average_points": 1.0,
    }
    assert grouped["trend"]["unknown"]["trades"] == 1
    assert grouped["setup"]["OR"]["trades"] == 2
    assert grouped["setup"]["WR"]["net_points"] == -2.0
