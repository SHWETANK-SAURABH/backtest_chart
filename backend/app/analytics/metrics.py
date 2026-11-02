"""Performance statistics from completed trades, in theoretical index points.

Undefined values are None rather than a made-up number: profit factor with no losing trades,
win rate with no trades, Sharpe ratio with fewer than two sessions or no variation.
"""

import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Protocol

TRADING_DAYS_PER_YEAR = 252


class TradeLike(Protocol):
    @property
    def trading_date(self) -> date: ...
    @property
    def exit_time(self) -> datetime: ...
    @property
    def entry_price(self) -> float: ...
    @property
    def net_points(self) -> float: ...
    @property
    def holding_seconds(self) -> int: ...


@dataclass(frozen=True)
class TradeStatistics:
    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: float | None
    gross_profit_points: float
    gross_loss_points: float
    net_points: float
    profit_factor: float | None
    expectancy_points: float | None
    average_trade_points: float | None
    average_win_points: float | None
    average_loss_points: float | None
    max_consecutive_wins: int
    max_consecutive_losses: int
    average_holding_seconds: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EquityPoint:
    time: datetime
    cumulative_points: float
    drawdown_points: float


@dataclass(frozen=True)
class PeriodPerformance:
    period: date  # session date, or first day of the month
    trades: int
    wins: int
    losses: int
    net_points: float


def trade_statistics(trades: Sequence[TradeLike]) -> TradeStatistics:
    results = [t.net_points for t in trades]
    wins = [r for r in results if r > 0]
    losses = [r for r in results if r < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    total = len(results)

    longest = {True: 0, False: 0}
    current_kind, run = None, 0
    for result in results:
        kind = True if result > 0 else False if result < 0 else None
        run = (
            run + 1 if kind is not None and kind == current_kind else (1 if kind is not None else 0)
        )
        current_kind = kind
        if kind is not None:
            longest[kind] = max(longest[kind], run)

    average = sum(results) / total if total else None
    win_rate = len(wins) / total if total else None
    average_win = gross_profit / len(wins) if wins else None
    average_loss = -gross_loss / len(losses) if losses else None
    expectancy = None
    if win_rate is not None:
        expectancy = win_rate * (average_win or 0.0) + (len(losses) / total) * (average_loss or 0.0)

    return TradeStatistics(
        total_trades=total,
        winning_trades=len(wins),
        losing_trades=len(losses),
        breakeven_trades=total - len(wins) - len(losses),
        win_rate=win_rate,
        gross_profit_points=gross_profit,
        gross_loss_points=gross_loss,
        net_points=sum(results),
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else None,
        expectancy_points=expectancy,
        average_trade_points=average,
        average_win_points=average_win,
        average_loss_points=average_loss,
        max_consecutive_wins=longest[True],
        max_consecutive_losses=longest[False],
        average_holding_seconds=(sum(t.holding_seconds for t in trades) / total if total else None),
    )


def equity_curve(trades: Sequence[TradeLike]) -> list[EquityPoint]:
    """Cumulative points after each exit, and drawdown from the running peak. Starts from 0."""
    points: list[EquityPoint] = []
    cumulative, peak = 0.0, 0.0
    for trade in sorted(trades, key=lambda t: t.exit_time):
        cumulative += trade.net_points
        peak = max(peak, cumulative)
        points.append(EquityPoint(trade.exit_time, cumulative, peak - cumulative))
    return points


def max_drawdown(curve: Sequence[EquityPoint]) -> float | None:
    return max((p.drawdown_points for p in curve), default=None)


def daily_performance(
    trades: Sequence[TradeLike], sessions: Sequence[date]
) -> list[PeriodPerformance]:
    """One row per tested session, including sessions without trades."""
    by_day: dict[date, list[float]] = defaultdict(list)
    for trade in trades:
        by_day[trade.trading_date].append(trade.net_points)
    return [
        PeriodPerformance(
            day,
            len(by_day[day]),
            sum(1 for r in by_day[day] if r > 0),
            sum(1 for r in by_day[day] if r < 0),
            sum(by_day[day]),
        )
        for day in sorted(set(sessions) | set(by_day))
    ]


def monthly_performance(daily: Sequence[PeriodPerformance]) -> list[PeriodPerformance]:
    months: dict[date, list[PeriodPerformance]] = defaultdict(list)
    for row in daily:
        months[row.period.replace(day=1)].append(row)
    return [
        PeriodPerformance(
            month,
            sum(r.trades for r in rows),
            sum(r.wins for r in rows),
            sum(r.losses for r in rows),
            sum(r.net_points for r in rows),
        )
        for month, rows in sorted(months.items())
    ]


SHARPE_ASSUMPTIONS = {
    "series": "net index points per tested session, including sessions without trades",
    "frequency": "daily",
    "annualisation": f"mean / sample standard deviation x sqrt({TRADING_DAYS_PER_YEAR})",
    "risk_free_rate": 0,
    "note": "Computed on points, not percentage returns, because spot results are points",
}


def sharpe_ratio(daily: Sequence[PeriodPerformance]) -> float | None:
    values = [row.net_points for row in daily]
    if len(values) < 2:
        return None
    deviation = statistics.stdev(values)
    if deviation == 0:
        return None
    return statistics.fmean(values) / deviation * math.sqrt(TRADING_DAYS_PER_YEAR)


def unit_summary(trades: Sequence[TradeLike]) -> dict[str, Any]:
    """Results in each unit the prompt distinguishes, with the reason when one is unavailable."""
    percents = [t.net_points / t.entry_price * 100 for t in trades if t.entry_price]
    return {
        "points": {"net": sum(t.net_points for t in trades)},
        "percent_of_index": {
            "sum_of_trade_returns": sum(percents) if percents else None,
            "average_trade_return": statistics.fmean(percents) if percents else None,
            "note": "Each trade's net points as a percent of its entry level, uncompounded",
        },
        "hypothetical_monetary": {
            "value": None,
            "reason": "NIFTY 50 spot has no contract multiplier; needs a futures or options model",
        },
        "actual_monetary": {
            "value": None,
            "reason": "Not available: spot index results are theoretical",
        },
    }
