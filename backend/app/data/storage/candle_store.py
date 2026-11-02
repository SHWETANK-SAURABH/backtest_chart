"""Immutable Parquet candle storage, queried with DuckDB.

Layout: candles/symbol=X/timeframe=Y/year=YYYY/month=MM/<provider>-<content hash>.parquet

Files are named by content and never overwritten. A dataset version is a manifest listing its
files, so it keeps resolving to the same data after later downloads add new versions.
"""

import gzip
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb
import polars as pl

from app.data.ingestion.normalize import CANDLE_SCHEMA, CONTENT_COLUMNS


class DatasetIntegrityError(Exception):
    """A dataset file is missing or its bytes differ from the manifest."""


@dataclass(frozen=True)
class WrittenDataset:
    content_hash: str
    manifest: dict[str, Any]
    row_count: int
    start_date: date | None
    end_date: date | None


def _content_hash(frame: pl.DataFrame) -> str:
    """Hash candle values only, so re-downloading identical data yields an identical hash."""
    content = frame.sort("timestamp").select(CONTENT_COLUMNS).write_csv()
    return hashlib.sha256(content.encode()).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def merge_candles(base: pl.DataFrame, new: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    """Combine a prior version with new candles. Returns the result and the revision count.

    Unchanged rows keep their original ingestion time. A candle the provider has revised takes the
    new values; the earlier values remain available in the prior immutable version.
    """
    changed = new.join(base.select(CONTENT_COLUMNS), on=CONTENT_COLUMNS, how="anti", nulls_equal=True)
    revised = changed.join(base.select("timestamp"), on="timestamp", how="semi").height
    kept = base.join(changed.select("timestamp"), on="timestamp", how="anti")
    return pl.concat([kept, changed]).sort("timestamp"), revised


class CandleStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def write_dataset(self, frame: pl.DataFrame) -> WrittenDataset:
        files = []
        partitioned = frame.with_columns(
            pl.col("trading_date").dt.year().alias("_year"),
            pl.col("trading_date").dt.month().alias("_month"),
        )
        for (year, month), part in sorted(
            partitioned.group_by(["_year", "_month"]), key=lambda item: str(item[0])
        ):
            files.append(self._write_partition(part.drop("_year", "_month"), year, month))
        files.sort(key=lambda item: item["path"])

        digest = hashlib.sha256()
        for item in files:
            digest.update(item["content_hash"].encode())
        return WrittenDataset(
            content_hash=digest.hexdigest(),
            manifest={"files": files},
            row_count=frame.height,
            start_date=frame["trading_date"].min() if frame.height else None,  # type: ignore[arg-type]
            end_date=frame["trading_date"].max() if frame.height else None,  # type: ignore[arg-type]
        )

    def _write_partition(self, part: pl.DataFrame, year: Any, month: Any) -> dict[str, Any]:
        part = part.sort("timestamp")
        content_hash = _content_hash(part)
        directory = (
            Path("candles")
            / f"symbol={part['symbol'][0]}"
            / f"timeframe={part['timeframe'][0]}"
            / f"year={year:04d}"
            / f"month={month:02d}"
        )
        relative = directory / f"{part['provider'][0]}-{content_hash[:16]}.parquet"
        target = self.root / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(f".{uuid4().hex}.tmp")
            part.write_parquet(temporary, compression="zstd")
            os.replace(temporary, target)
        return {
            "path": relative.as_posix(),
            "rows": part.height,
            "content_hash": content_hash,
            "file_sha256": _file_sha256(target),
        }

    def verify(self, manifest: dict[str, Any]) -> None:
        for item in manifest["files"]:
            path = self.root / item["path"]
            if not path.exists():
                raise DatasetIntegrityError(f"Missing dataset file: {item['path']}")
            if _file_sha256(path) != item["file_sha256"]:
                raise DatasetIntegrityError(f"Dataset file has changed: {item['path']}")

    def query(
        self, manifest: dict[str, Any], start: date | None = None, end: date | None = None
    ) -> pl.DataFrame:
        """Candles for a dataset version in chronological order, using DuckDB."""
        paths = [str(self.root / item["path"]) for item in manifest["files"]]
        if not paths:
            return pl.DataFrame(schema=CANDLE_SCHEMA)
        # Epoch microseconds are absolute, so results cannot depend on the machine's timezone.
        columns = ", ".join(
            f"epoch_us({name}) AS {name}" if name in ("timestamp", "ingested_at") else name
            for name in CANDLE_SCHEMA
        )
        with duckdb.connect(":memory:") as connection:
            result = connection.execute(
                f"SELECT {columns} FROM read_parquet(?) "
                "WHERE (? IS NULL OR trading_date >= ?) AND (? IS NULL OR trading_date <= ?) "
                "ORDER BY timestamp",
                [paths, start, start, end, end],
            ).pl()
        return result.with_columns(
            pl.col("timestamp", "ingested_at").cast(pl.Datetime("us")).dt.replace_time_zone("UTC")
        ).cast(CANDLE_SCHEMA)  # type: ignore[arg-type]


class StagingStore:
    """Per-job storage of downloaded chunks, so an interrupted job resumes without re-downloading.

    The provider's original payloads are kept permanently under raw/ for provenance.
    """

    def __init__(self, root: Path, provider: str, job_id: str) -> None:
        self._raw = Path(root) / "raw" / provider / job_id
        self._staging = Path(root) / "staging" / job_id

    def save_chunk(self, name: str, frame: pl.DataFrame, raw_payload: dict[str, Any]) -> None:
        self._raw.mkdir(parents=True, exist_ok=True)
        self._staging.mkdir(parents=True, exist_ok=True)
        with gzip.open(self._raw / f"{name}.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(raw_payload, handle)
        temporary = self._staging / f"{name}.{uuid4().hex}.tmp"
        frame.write_parquet(temporary)
        os.replace(temporary, self._staging / f"{name}.parquet")

    def load_chunks(self) -> pl.DataFrame:
        paths = sorted(self._staging.glob("*.parquet")) if self._staging.exists() else []
        if not paths:
            return pl.DataFrame(schema=CANDLE_SCHEMA)
        return pl.concat([pl.read_parquet(path) for path in paths]).cast(CANDLE_SCHEMA)  # type: ignore[arg-type]

    def clear_staging(self) -> None:
        if self._staging.exists():
            for path in self._staging.iterdir():
                path.unlink()
            self._staging.rmdir()
