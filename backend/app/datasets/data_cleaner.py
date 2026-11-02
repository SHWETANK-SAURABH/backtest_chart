"""Removes records unsuitable for training, and reports every removal. Values are never altered."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CleaningReport:
    input_records: int = 0
    output_records: int = 0
    removed: dict[str, int] = field(default_factory=dict)


def clean(
    records: list[dict[str, Any]], drop_without_levels: bool = True
) -> tuple[list[dict[str, Any]], CleaningReport]:
    """Drop duplicate timestamps, records missing a close, and (optionally) candles evaluated
    before enough daily history existed for the strategy's levels."""
    removed: Counter[str] = Counter()
    seen: set[str] = set()
    kept = []
    for record in records:
        if record["timestamp"] in seen:
            removed["duplicate_timestamp"] += 1
            continue
        seen.add(record["timestamp"])
        if record["features"]["market_context"]["close"] is None:
            removed["missing_close"] += 1
            continue
        if drop_without_levels and "NO_MTZ_LEVELS" in record["labels"]["decision"]["reason_codes"]:
            removed["no_strategy_levels"] += 1
            continue
        kept.append(record)
    return kept, CleaningReport(len(records), len(kept), dict(removed))
