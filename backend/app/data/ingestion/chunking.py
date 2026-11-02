"""Splitting a date range into provider-sized requests."""

from datetime import date, timedelta


def plan_chunks(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    """Inclusive, non-overlapping ranges that span at most max_days calendar days each."""
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    if max_days < 1:
        raise ValueError("max_days must be at least 1")
    chunks = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=max_days - 1), end)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks
