"""Explanations built only from the reason codes the engine actually produced."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.strategy.engine import EntrySignal

PATTERN_NAMES = {
    "OR": "outside reversal",
    "DR": "doji reversal",
    "ER": "extreme reversal",
    "WR": "wick reversal",
}
ZONE_NAMES = {"DAILY_MTZ": "daily MTZ", "WEEKLY_MTZ": "weekly MTZ"}
BOOK_SETUP_NAMES = {
    "BREAKAWAY": "Breakaway",
    "MAGNET": "Magnet (gap fill)",
    "CPR_PULLBACK": "CPR pull-back",
    "CPR_FADE": "CPR fade after a rejected open",
    "TREND_CHANGE": "Trend change after a strong day",
    "PERSON_PLAN": "John Person's trend plan",
    "FLOOR_PIVOT": "Floor pivot, trend filtered",
    "CAM_REVERSAL": "Camarilla H3/L3 reversal",
    "CAM_PATTERN": "Camarilla reversal pattern",
    "CAM_BREAKOUT": "Camarilla H4/L4 breakout",
}

MESSAGES = {
    "NO_MTZ_LEVELS": "No MTZ levels yet: not enough completed daily history.",
    "NO_REVERSAL_SIGNAL": "No reversal candle confirmed on this bar.",
    "REVERSAL_NOT_AT_MTZ": (
        "A reversal candle confirmed, but the candle before it did not touch an MTZ."
    ),
    "CONFLICTING_SIGNALS": "Long and short reversal candles confirmed together, so no trade.",
    "NO_TARGET_ZONE": "Reversal at an MTZ, but no other MTZ lies in the trade direction to target.",
    "INVALID_STOP": "Reversal at an MTZ, but the signal candle's stop is not beyond the close.",
    "CPR_SIDEWAYS_NO_TRADE": "The daily CPR histogram is Sideways, so no trades today.",
    "R2_S2_REACHED": "Price has touched the daily R2 or S2, so no new entries today.",
    "EXIT_MTZ_TARGET": "Exit at the target MTZ.",
    "NO_DAY_DIRECTION": (
        "No day direction yet: the opening bias gave none and no 15-minute candle has closed "
        "beyond the CPR."
    ),
    "AGAINST_DAY_DIRECTION": "The signal is against the day's direction.",
    "DAY_DIRECTION_OPENING_BIAS": "With the day's direction from the 2-day CPR and opening bias.",
    "DAY_DIRECTION_CPR_BREAK_15M": (
        "With the day's direction from the latest 15-minute close beyond the CPR."
    ),
    "ADR_COMPLETE": "The session's range has reached the ADR.",
    "ADR_DIRECTION_UNCLEAR": "The candle completing the ADR made both the high and the low.",
    "ADR_LONG": "ADR trade: long against the move down that completed the ADR.",
    "ADR_SHORT": "ADR trade: short against the move up that completed the ADR.",
    "NO_LEVELS": "No CPR or Camarilla levels yet: not enough completed daily history.",
    "NO_BOOK_SETUP": "No Pivot Boss setup on this candle.",
    "AGAINST_WEEKLY_BIAS": "A setup fired against the weekly bias.",
    "NO_ROOM_TO_TARGET": "A setup fired, but price is already at or beyond its target.",
    "EXIT_FIXED_TARGET": "Exit at the fixed pivot target.",
    "EXIT_ATR_TRAIL": "Exit at the target or on a 1.5 ATR trailing stop.",
    "AGAINST_DAY_TREND": "A setup fired against the day's trend from the two-day relationship.",
    "AGAINST_PIVOT_TREND": "A setup fired against the floor-pivot (S1/R1) trend.",
    "AGAINST_WEEKLY_TREND": "A setup fired against the weekly trend.",
    "TREND_NOT_CLEAR": (
        "A trend setup fired, but the S1/R1, day and weekly trends do not all agree."
    ),
    "EXIT_EMA_TRAIL": (
        "Trending CPR: no target; exit when a candle of the opposite colour closes beyond the "
        "5 EMA."
    ),
}


def _describe(code: str) -> str | None:
    if code in MESSAGES:
        return MESSAGES[code]
    pattern, _, side = code.partition("_")
    if pattern in PATTERN_NAMES and side in ("LONG", "SHORT"):
        return f"{PATTERN_NAMES[pattern].capitalize()} ({side.lower()}) confirmed."
    setup, _, direction = code.rpartition("_")
    if setup in BOOK_SETUP_NAMES and direction in ("LONG", "SHORT"):
        return f"{BOOK_SETUP_NAMES[setup]} ({direction.lower()})."
    if code.startswith("TRIGGER_") and code[8:] in PATTERN_NAMES:
        return f"Triggered by a {PATTERN_NAMES[code[8:]]}."
    if code.startswith("AT_") and code[3:] in ZONE_NAMES:
        return f"The signal touched the {ZONE_NAMES[code[3:]]}."
    if code.startswith("TARGET_") and code[7:] in ZONE_NAMES:
        return f"Target is the {ZONE_NAMES[code[7:]]}."
    if code.startswith("TARGET_"):
        return f"Target is {code[7:]}."
    return None


def explain(codes: list[str], entry: "EntrySignal | None") -> str:
    parts = [text for text in (_describe(code) for code in codes) if text]
    if entry is not None:
        target = "none" if entry.target is None else f"{entry.target:.2f}"
        parts.append(f"Stop {entry.stop_loss:.2f}, target {target}.")
    return " ".join(parts)
