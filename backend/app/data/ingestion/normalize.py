"""Conversion of candles to the storage frame, and de-duplication."""

from collections.abc import Iterable
from dataclasses import dataclass

import polars as pl

from app.domain.candle import EXCHANGE_TIMEZONE, Candle

CANDLE_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "symbol": pl.String,
    "timeframe": pl.String,
    "timestamp": pl.Datetime("us", "UTC"),
    "trading_date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
    "provider": pl.String,
    "ingested_at": pl.Datetime("us", "UTC"),
}
CONTENT_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


@dataclass(frozen=True)
class DedupeStats:
    exact_duplicates: int
    conflicting_duplicates: int


def to_frame(candles: Iterable[Candle]) -> pl.DataFrame:
    rows = [
        {
            "symbol": c.symbol,
            "timeframe": c.timeframe.value,
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
            "provider": c.provider,
            "ingested_at": c.ingested_at,
        }
        for c in candles
    ]
    schema = {name: dtype for name, dtype in CANDLE_SCHEMA.items() if name != "trading_date"}
    frame = pl.DataFrame(rows, schema=schema)
    return frame.with_columns(
        pl.col("timestamp").dt.convert_time_zone(EXCHANGE_TIMEZONE).dt.date().alias("trading_date")
    ).select(list(CANDLE_SCHEMA))


def deduplicate(frame: pl.DataFrame) -> tuple[pl.DataFrame, DedupeStats]:
    """Keep the first row per timestamp, and count how many repeats disagreed with it."""
    unique_content = frame.unique(subset=CONTENT_COLUMNS, keep="first", maintain_order=True)
    result = unique_content.unique(subset=["timestamp"], keep="first", maintain_order=True)
    stats = DedupeStats(
        exact_duplicates=frame.height - unique_content.height,
        conflicting_duplicates=unique_content.height - result.height,
    )
    return result.sort("timestamp"), stats
