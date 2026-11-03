"""Builds 15-minute candles from verified 5-minute candles.

NSE sessions start at 09:15 (and special sessions on quarter hours, such as 18:00 and 18:15), so
each 15-minute candle covers three 5-minute candles aligned to the clock: 09:15, 09:30, and so on.
A 15-minute candle is built only from three present 5-minute candles; a group with any candle
missing is dropped rather than shown as a complete candle.
"""

from datetime import timedelta

import polars as pl

from app.domain.enums import Timeframe

BAR_LENGTHS = {Timeframe.M5: timedelta(minutes=5), Timeframe.M15: timedelta(minutes=15)}


def resample(candles: pl.DataFrame, timeframe: Timeframe) -> pl.DataFrame:
    """Candles in `timeframe`, from 5-minute candles."""
    if timeframe == Timeframe.M5 or candles.is_empty():
        return candles
    if timeframe != Timeframe.M15:
        raise ValueError(f"Cannot build {timeframe} candles from 5-minute data")
    grouped = (
        candles.sort("timestamp")
        .with_columns(bucket=pl.col("timestamp").dt.truncate("15m"))
        .group_by("trading_date", "bucket", maintain_order=True)
        .agg(
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
            pl.len().alias("parts"),
        )
    )
    return (
        grouped.filter(pl.col("parts") == 3)
        .drop("parts")
        .rename({"bucket": "timestamp"})
        .select("timestamp", "trading_date", "open", "high", "low", "close")
    )
