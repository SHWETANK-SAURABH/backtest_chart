"""Strategy parameters. Defaults are the Pine script's input defaults."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.strategy.periods import Period

STRATEGY_NAME = "MTZ Reversal"
# Bump when strategy behaviour changes. The code hash also changes with any source edit.
IMPLEMENTATION_VERSION = "6.0.0"
PATTERNS = ("OR", "DR", "ER", "WR")
# Pivot Boss setups, in the order they are checked when several fire on one candle.
BOOK_SETUPS = (
    "BREAKAWAY",
    "MAGNET",
    "TREND_CHANGE",
    "CPR_PULLBACK",
    "CPR_FADE",
    "PERSON_PLAN",
    "FLOOR_PIVOT",
    "CAM_REVERSAL",
    "CAM_PATTERN",
    "CAM_BREAKOUT",
)
# Hot zone scalp (strategy4.txt) zone types, and the defaults chosen by the owner.
HZ_TYPES = ("MTF", "GPZ", "DPZ", "MTF_STAR", "PP_CC")
HZ_DEFAULT_TYPES = ("MTF", "GPZ")
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
    strategy: str = "mtz_reversal"
    book_setups: tuple[str, ...] = BOOK_SETUPS
    weekly_filter: bool = True
    trend_analysis: bool = False
    clear_trend: bool = False
    hz_types: tuple[str, ...] = HZ_DEFAULT_TYPES
    hz_min_score: int = Field(2, ge=2, le=4)
    hz_panel_gate: bool = False


class StrategyKind(StrEnum):
    MTZ_REVERSAL = "mtz_reversal"
    PIVOT_BOSS = "pivot_boss"
    HOT_ZONE = "hot_zone"


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

    strategy: StrategyKind = StrategyKind.MTZ_REVERSAL
    entry_patterns: tuple[str, ...] = PATTERNS
    mtz: MtzChoice = MtzChoice.BOTH
    cpr_thresholds: tuple[float, float, float] = CPR_THRESHOLDS
    # Longs or shorts only, from the 2-day CPR relationship and opening bias.
    day_direction: bool = True
    # One trade against the move once the day's range reaches the ADR.
    adr_trade: bool = True
    # Pivot Boss only: which setups may enter, and trading only with the weekly bias.
    book_setups: tuple[str, ...] = BOOK_SETUPS
    weekly_filter: bool = True
    # Pivot Boss only: the 7 relationships, the S1/R1 trend and the weekly trend gate every setup.
    trend_analysis: bool = False
    # Pivot Boss only: trend setups need the S1/R1, day and weekly trends all on their side.
    clear_trend: bool = False
    # Hot zone scalp only: which zones trade, the MTF confluence minimum score, and whether the
    # trade direction panel must also allow the side.
    hz_types: tuple[str, ...] = HZ_DEFAULT_TYPES
    hz_min_score: int = Field(2, ge=2, le=4)
    hz_panel_gate: bool = False

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

    @field_validator("book_setups")
    @classmethod
    def check_setups(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = set(value) - set(BOOK_SETUPS)
        if unknown:
            raise ValueError(f"Unknown setups: {', '.join(sorted(unknown))}")
        if not value:
            raise ValueError("Choose at least one setup")
        return tuple(s for s in BOOK_SETUPS if s in value)

    @field_validator("hz_types")
    @classmethod
    def check_zone_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = set(value) - set(HZ_TYPES)
        if unknown:
            raise ValueError(f"Unknown zone types: {', '.join(sorted(unknown))}")
        if not value:
            raise ValueError("Choose at least one zone type")
        return tuple(t for t in HZ_TYPES if t in value)

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
                "strategy": self.strategy.value,
                "book_setups": self.book_setups,
                "weekly_filter": self.weekly_filter,
                "trend_analysis": self.trend_analysis,
                "clear_trend": self.clear_trend,
                "hz_types": self.hz_types,
                "hz_min_score": self.hz_min_score,
                "hz_panel_gate": self.hz_panel_gate,
            }
        )
