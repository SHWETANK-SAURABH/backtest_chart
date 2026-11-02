"""Backtest configuration."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ExecutionMethod


class SameCandlePolicy(StrEnum):
    """What to assume when one candle touches both the stop and the target.

    Only the conservative choice exists: without lower-timeframe data the order is unknown, and
    assuming the favourable outcome would overstate results.
    """

    STOP_FIRST = "stop_first"


class ExecutionSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: ExecutionMethod = ExecutionMethod.NEXT_OPEN
    # Applied against the trade on entries, stop exits and square-offs. Target exits are limit
    # orders and fill at the target, or at a better opening price after a gap.
    slippage_points: float = Field(0.0, ge=0, le=100)
    same_candle_policy: SameCandlePolicy = SameCandlePolicy.STOP_FIRST


class RiskSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_trades_per_day: int | None = Field(None, ge=1)
    max_daily_loss_points: float | None = Field(None, gt=0)


class CapitalAssumptions(BaseModel):
    """Recorded for context only. Spot index results are points, never rupees."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_capital: float = Field(1_000_000, gt=0)
    currency: str = "INR"
