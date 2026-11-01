"""Parquet storage and DuckDB queries, using clearly labelled mock candles."""

import time
from datetime import date
from pathlib import Path

import pytest

from app.data.ingestion.normalize import to_frame
from app.data.storage.candle_store import CandleStore, DatasetIntegrityError, merge_candles
from tests.support.mock_market_data import mock_session_candles

JUNE = date(2025, 6, 16)
JULY = date(2025, 7, 1)


def frame(*days: date, price: float = 100.0):
    return to_frame([c for day in days for c in mock_session_candles(day, price)])


def test_files_are_partitioned_by_symbol_timeframe_year_and_month(tmp_path: Path) -> None:
    written = CandleStore(tmp_path).write_dataset(frame(JUNE, JULY))
    paths = [item["path"] for item in written.manifest["files"]]
    assert len(paths) == 2
    assert paths[0].startswith("candles/symbol=NIFTY50/timeframe=5m/year=2025/month=06/")
    assert paths[1].startswith("candles/symbol=NIFTY50/timeframe=5m/year=2025/month=07/")
    assert written.row_count == 150
    assert written.start_date == JUNE
    assert written.end_date == JULY


def test_query_returns_chronological_timezone_aware_rows(tmp_path: Path) -> None:
    store = CandleStore(tmp_path)
    original = frame(JUNE, JULY)
    written = store.write_dataset(original)
    result = store.query(written.manifest)
    assert result.equals(original.sort("timestamp"))
    assert result.schema["timestamp"].time_zone == "UTC"


@pytest.mark.parametrize("zone", ["UTC", "Asia/Kolkata", "America/New_York"])
def test_query_timestamps_do_not_depend_on_the_machine_timezone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, zone: str
) -> None:
    monkeypatch.setenv("TZ", zone)
    if hasattr(time, "tzset"):
        time.tzset()
    store = CandleStore(tmp_path)
    original = frame(JUNE)
    result = store.query(store.write_dataset(original).manifest)
    assert result["timestamp"].to_list() == original["timestamp"].to_list()
    assert result["ingested_at"].to_list() == original["ingested_at"].to_list()


def test_query_filters_by_trading_date(tmp_path: Path) -> None:
    store = CandleStore(tmp_path)
    written = store.write_dataset(frame(JUNE, JULY))
    assert store.query(written.manifest, start=JULY)["trading_date"].unique().to_list() == [JULY]
    assert store.query(written.manifest, end=JUNE)["trading_date"].unique().to_list() == [JUNE]


def test_identical_content_hashes_the_same_even_when_reingested_later(tmp_path: Path) -> None:
    store = CandleStore(tmp_path)
    first = store.write_dataset(frame(JUNE))
    later = frame(JUNE).with_columns(ingested_at=frame(JUNE)["ingested_at"].dt.offset_by("1d"))
    assert store.write_dataset(later).content_hash == first.content_hash


def test_different_content_gets_a_new_hash_and_old_files_survive(tmp_path: Path) -> None:
    store = CandleStore(tmp_path)
    first = store.write_dataset(frame(JUNE))
    second = store.write_dataset(frame(JUNE, price=200.0))
    assert second.content_hash != first.content_hash
    assert store.query(first.manifest)["open"][0] == 100.0
    assert store.query(second.manifest)["open"][0] == 200.0


def test_verify_detects_changed_and_missing_files(tmp_path: Path) -> None:
    store = CandleStore(tmp_path)
    written = store.write_dataset(frame(JUNE))
    store.verify(written.manifest)
    target = tmp_path / written.manifest["files"][0]["path"]
    target.write_bytes(b"tampered")
    with pytest.raises(DatasetIntegrityError, match="changed"):
        store.verify(written.manifest)
    target.unlink()
    with pytest.raises(DatasetIntegrityError, match="Missing"):
        store.verify(written.manifest)


def test_merge_adds_new_rows_and_counts_revisions_only() -> None:
    merged, revised = merge_candles(frame(JUNE), frame(JULY))
    assert merged.height == 150
    assert revised == 0

    merged, revised = merge_candles(frame(JUNE), frame(JUNE, price=200.0))
    assert merged.height == 75
    assert revised == 75
    assert merged["open"][0] == 200.0


def test_merge_keeps_original_ingestion_time_for_unchanged_rows() -> None:
    base = frame(JUNE)
    later = base.with_columns(ingested_at=base["ingested_at"].dt.offset_by("1d"))
    merged, revised = merge_candles(base, later)
    assert revised == 0
    assert merged["ingested_at"].to_list() == base["ingested_at"].to_list()


def test_merge_treats_missing_volume_as_equal() -> None:
    _, revised = merge_candles(frame(JUNE), frame(JUNE))
    assert revised == 0
