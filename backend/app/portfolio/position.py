"""Open positions, completed trades and daily risk limits. Results are theoretical index points."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.domain.enums import Side


@dataclass
class Position:
    side: Side
    trading_date: date
    entry_time: datetime
    entry_price: float
    stop_loss: float
    target: float
    entry_reasons: list[str]
    entry_context: dict[str, Any]
    entry_notes: list[str] = field(default_factory=list)

    def points(self, exit_price: float) -> float:
        if self.side == Side.LONG:
            return exit_price - self.entry_price
        return self.entry_price - exit_price


@dataclass(frozen=True)
class ClosedTrade:
    number: int
    trading_date: date
    side: Side
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_loss: float
    target: float
    exit_reason: str
    gross_points: float
    cost_points: float
    net_points: float
    entry_reasons: list[str]
    entry_context: dict[str, Any]
    exit_context: dict[str, Any]
    notes: list[str]

    @property
    def holding_seconds(self) -> int:
        return int((self.exit_time - self.entry_time).total_seconds())


class DailyRiskTracker:
    """Daily trade count and realised loss limits. None disables a limit."""

    def __init__(self, max_trades_per_day: int | None, max_daily_loss_points: float | None) -> None:
        self._max_trades = max_trades_per_day
        self._max_loss = max_daily_loss_points
        self._day: date | None = None
        self.trades_today = 0
        self.net_points_today = 0.0

    def _roll(self, day: date) -> None:
        if day != self._day:
            self._day = day
            self.trades_today = 0
            self.net_points_today = 0.0

    def entry_block_reason(self, day: date) -> str | None:
        self._roll(day)
        if self._max_trades is not None and self.trades_today >= self._max_trades:
            return "DAILY_TRADE_LIMIT"
        if self._max_loss is not None and self.net_points_today <= -self._max_loss:
            return "DAILY_LOSS_LIMIT"
        return None

    def record_entry(self, day: date) -> None:
        self._roll(day)
        self.trades_today += 1

    def record_exit(self, day: date, net_points: float) -> None:
        self._roll(day)
        self.net_points_today += net_points
