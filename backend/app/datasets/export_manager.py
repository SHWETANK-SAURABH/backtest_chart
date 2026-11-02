"""Writes dataset splits as JSONL (nested records), CSV and Parquet (flattened columns)."""

import csv
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.domain.enums import ExportFormat

DATASET_FORMATS = (ExportFormat.JSONL, ExportFormat.CSV, ExportFormat.PARQUET)


def flatten(record: dict[str, Any]) -> dict[str, Any]:
    """Nested keys joined with dots, such as 'features.market_context.close'. Lists become JSON."""
    flat: dict[str, Any] = {}

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                walk(f"{prefix}.{key}" if prefix else key, inner)
        elif isinstance(value, list):
            flat[prefix] = json.dumps(value)
        else:
            flat[prefix] = value

    walk("", record)
    return flat


def unflatten(row: dict[str, Any]) -> dict[str, Any]:
    """The inverse of flatten for list fields named in the schema."""
    record: dict[str, Any] = {}
    for key, value in row.items():
        node = record
        *parents, leaf = key.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        if leaf in ("reason_codes", "reversal_signals") and isinstance(value, str):
            value = json.loads(value)
        node[leaf] = value
    return record


def _write_atomic(path: Path, write: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    write(temporary)
    os.replace(temporary, path)


def write(
    records: list[dict[str, Any]], fmt: ExportFormat, path: Path, metadata: dict[str, Any]
) -> str:
    """Write one split and return its SHA-256."""
    if fmt == ExportFormat.JSONL:

        def write_jsonl(target: Path) -> None:
            with target.open("w", encoding="utf-8", newline="\n") as handle:
                for record in records:
                    handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")

        _write_atomic(path, write_jsonl)
    elif fmt == ExportFormat.CSV:
        rows = [flatten(r) for r in records]
        columns = list(dict.fromkeys(k for row in rows for k in row))

        def write_csv(target: Path) -> None:
            with target.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)

        _write_atomic(path, write_csv)
    elif fmt == ExportFormat.PARQUET:
        rows = [flatten(r) for r in records]
        columns = list(dict.fromkeys(k for row in rows for k in row))
        table = (
            pa.Table.from_pylist([{c: row.get(c) for c in columns} for row in rows])
            if rows
            else pa.table({})
        )
        table = table.replace_schema_metadata(
            {b"dataset_metadata": json.dumps(metadata, default=str).encode()}
        )
        _write_atomic(path, lambda target: pq.write_table(table, target))
    else:
        raise ValueError(f"Unsupported dataset format: {fmt}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_parquet(path: Path) -> list[dict[str, Any]]:
    return [unflatten(row) for row in pq.read_table(path).to_pylist()]
