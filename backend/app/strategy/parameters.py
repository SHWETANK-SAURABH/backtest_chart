"""Strategy parameters. Defaults are the Pine script's input defaults."""

from pydantic import BaseModel, ConfigDict, Field

from app.strategy.periods import Period

STRATEGY_NAME = "MTZ Reversal"
# Bump when strategy behaviour changes. The code hash also changes with any source edit.
IMPLEMENTATION_VERSION = "1.0.0"


class StrategyParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    adr_length: int = Field(10, ge=1)
    ema_fast_length: int = Field(5, ge=1)
    ema_slow_length: int = Field(20, ge=1)
    hot_zone_tolerance: float = Field(0.25, ge=0.05, le=1.0)
    hot_zone_min_score: int = Field(2, ge=2, le=3)
    magnet_min_gap: float = Field(0.15, ge=0.05, le=1.0)
    mtz_periods: tuple[Period, ...] = (Period.DAY, Period.WEEK)
