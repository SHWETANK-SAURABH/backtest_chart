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

MESSAGES = {
    "NO_MTZ_LEVELS": "No MTZ levels yet: not enough completed daily history.",
    "NO_REVERSAL_SIGNAL": "No reversal candle confirmed on this bar.",
    "REVERSAL_NOT_AT_MTZ": (
        "A reversal candle confirmed, but the candle before it did not touch an MTZ."
    ),
    "CONFLICTING_SIGNALS": "Long and short reversal candles confirmed together, so no trade.",
    "NO_TARGET_ZONE": "Reversal at an MTZ, but no other MTZ lies in the trade direction to target.",
    "INVALID_STOP": "Reversal at an MTZ, but the signal candle's stop is not beyond the close.",
}


def _describe(code: str) -> str | None:
    if code in MESSAGES:
        return MESSAGES[code]
    pattern, _, side = code.partition("_")
    if pattern in PATTERN_NAMES and side in ("LONG", "SHORT"):
        return f"{PATTERN_NAMES[pattern].capitalize()} ({side.lower()}) confirmed."
    if code.startswith("AT_") and code[3:] in ZONE_NAMES:
        return f"The signal touched the {ZONE_NAMES[code[3:]]}."
    if code.startswith("TARGET_") and code[7:] in ZONE_NAMES:
        return f"Target is the {ZONE_NAMES[code[7:]]}."
    return None


def explain(codes: list[str], entry: "EntrySignal | None") -> str:
    parts = [text for text in (_describe(code) for code in codes) if text]
    if entry is not None:
        parts.append(f"Stop {entry.stop_loss:.2f}, target {entry.target:.2f}.")
    return " ".join(parts)
