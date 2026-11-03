"""Strategy parameters. Defaults are the Pine script's input defaults."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.strategy.periods import Period

STRATEGY_NAME = "MTZ Reversal"
# Bump when strategy behaviour changes. The code hash also changes with any source edit.
IMPLEMENTATION_VERSION = "3.0.0"
PATTERNS = ("OR", "DR", "ER", "WR")
# The script's CPR width histogram bounds, in percent: Trending, Possible Trending, Sideways.
CPR_THRESHOLDS = (0.25, 0.50, 0.75)


class StrategyParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    adr_length: int = Field(10, ge=1)
    ema_fast_length: int = Field(5, ge=1)
    ema_slow_length: int = Field(20, ge=1)
    hot_zone_tolerance: float = Field(0.25, ge=0.05, le=1.0)
    hot_zone_min_score: int = Field(2, ge=2, le=3)
    magnet_min_gap: float = Field(0.15, ge=0.05, le=1.0)
    mtz_periods: tuple[Period, ...] = (Period.DAY, Period.WEEK)
    entry_patterns: tuple[str, ...] = PATTERNS
    cpr_thresholds: tuple[float, float, float] = CPR_THRESHOLDS
    day_direction: bool = False
    adr_trade: bool = False


class MtzChoice(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    BOTH = "both"


MTZ_PERIODS = {
    MtzChoice.DAILY: (Period.DAY,),
    MtzChoice.WEEKLY: (Period.WEEK,),
    MtzChoice.BOTH: (Period.DAY, Period.WEEK),
}


class StrategyOptions(BaseModel):
    """Choices made per backtest, applied on top of the strategy version's parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_patterns: tuple[str, ...] = PATTERNS
    mtz: MtzChoice = MtzChoice.BOTH
    cpr_thresholds: tuple[float, float, float] = CPR_THRESHOLDS
    # Longs or shorts only, from the 2-day CPR relationship and opening bias.
    day_direction: bool = True
    # One trade against the move once the day's range reaches the ADR.
    adr_trade: bool = True

    @field_validator("entry_patterns")
    @classmethod
    def check_patterns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = set(value) - set(PATTERNS)
        if unknown:
            raise ValueError(f"Unknown patterns: {', '.join(sorted(unknown))}")
        if not value:
            raise ValueError("Choose at least one entry pattern")
        # Stored in a fixed order, so the same choice always hashes the same.
        return tuple(p for p in PATTERNS if p in value)

    @field_validator("cpr_thresholds")
    @classmethod
    def check_thresholds(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if not 0 < value[0] < value[1] < value[2] <= 10:
            raise ValueError("CPR width thresholds must rise, each above 0% and at most 10%")
        return value

    def apply(self, parameters: StrategyParameters) -> StrategyParameters:
        return parameters.model_copy(
            update={
                "entry_patterns": self.entry_patterns,
                "mtz_periods": MTZ_PERIODS[self.mtz],
                "cpr_thresholds": self.cpr_thresholds,
                "day_direction": self.day_direction,
                "adr_trade": self.adr_trade,
            }
        )
