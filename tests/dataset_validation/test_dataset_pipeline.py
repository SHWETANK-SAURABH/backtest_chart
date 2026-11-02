"""Dataset cleaning, labelling, splitting, export and validation on hand-built test records."""

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.datasets import export_manager
from app.datasets.data_cleaner import clean
from app.datasets.data_labeler import outcome_labels, trades_by_signal_time
from app.datasets.dataset_builder import DatasetBuildError, DatasetParameters, assign_splits
from app.datasets.dataset_validator import validate
from app.datasets.dataset_version_manager import content_hash
from app.datasets.schema import MARKET_CONTEXT_FEATURES, STRATEGY_STATE_FEATURES
from app.domain.enums import ExportFormat


def record(day: int, minute: int, split: str, action: str = "HOLD", decision_id: int = 1) -> dict:
    timestamp = f"2025-06-{day:02d}T09:{15 + minute:02d}:00+05:30"
    return {
        "timestamp": timestamp,
        "trading_date": f"2025-06-{day:02d}",
        "instrument": "NIFTY50",
        "timeframe": "5m",
        "features": {
            "market_context": dict.fromkeys(MARKET_CONTEXT_FEATURES) | {"close": 100.0},
            "strategy_state": dict.fromkeys(STRATEGY_STATE_FEATURES) | {"reversal_signals": []},
        },
        "labels": {
            "decision": {"action": action, "reason_codes": ["NO_REVERSAL_SIGNAL"]},
            "outcome": {
                "trade_taken": False, "trade_net_points": None, "trade_result": None,
                "exit_reason": None, "holding_seconds": None, "setup_outcome": "no_setup",
                "forward_return_points_1_bars": 0.5,
            },
        },
        "strategy_version": "1.0.0",
        "strategy_code_hash": "a" * 64,
        "dataset_version": "1.0",
        "data_version": {"intraday": "x", "daily": "y"},
        "source": {"backtest_id": "b", "decision_id": decision_id},
        "split": split,
    }  # fmt: skip


def dataset() -> list[dict]:
    rows = []
    for i, (day, split) in enumerate([(2, "train"), (3, "train"), (4, "validation"), (5, "test")]):
        rows += [record(day, m, split, decision_id=i * 10 + m + 1) for m in (0, 5)]
    return rows


def failed_checks(rows: list[dict]) -> set[str]:
    return {c["check"] for c in validate(rows)["checks"] if not c["passed"]}


def test_a_well_formed_dataset_passes() -> None:
    report = validate(dataset(), lambda ids: set(ids))
    assert report["passed"], report
    assert report["records"] == 8


def test_missing_field_is_caught() -> None:
    rows = dataset()
    rows[0]["strategy_version"] = None
    del rows[1]["labels"]["outcome"]["setup_outcome"]
    assert "missing_fields" in failed_checks(rows)


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r["labels"]["decision"].update(action="MAYBE"),
        lambda r: r["labels"]["outcome"].update(setup_outcome="great"),
        lambda r: r["labels"]["outcome"].update(trade_taken=True),  # but no trade_result
        lambda r: r.update(split="holdout"),
    ],
)
def test_invalid_labels_are_caught(change) -> None:
    rows = dataset()
    change(rows[0])
    assert "invalid_labels" in failed_checks(rows)


def test_duplicate_records_are_caught() -> None:
    rows = dataset()
    rows.insert(1, copy.deepcopy(rows[0]))
    assert "duplicate_records" in failed_checks(rows)


@pytest.mark.parametrize(
    "leak",
    [
        lambda r: r["features"]["market_context"].update(next_close=101.0),
        lambda r: r["features"]["strategy_state"].update(trade_result="win"),
        lambda r: r["features"]["market_context"].update(forward_return_points_1_bars=0.5),
        lambda r: r["features"].update(future={"close": 101.0}),
    ],
)
def test_future_information_in_features_is_caught(leak) -> None:
    rows = dataset()
    leak(rows[3])
    assert "future_feature_leakage" in failed_checks(rows)


def test_overlapping_splits_are_caught() -> None:
    rows = dataset()
    rows[2]["split"] = "validation"  # a train session, but placed in validation
    assert "chronological_splits" in failed_checks(rows)


def test_a_session_split_across_sets_is_caught() -> None:
    rows = dataset()
    rows[5]["split"] = "test"  # half of the validation session
    rows.append(rows.pop(5))
    assert "chronological_splits" in failed_checks(rows)


def test_mixed_strategy_versions_are_caught() -> None:
    rows = dataset()
    rows[-1]["strategy_code_hash"] = "b" * 64
    assert "consistent_strategy_version" in failed_checks(rows)


def test_invalid_source_references_are_caught() -> None:
    rows = dataset()
    report = validate(rows, lambda ids: set(ids) - {1})
    assert "valid_source_references" in {c["check"] for c in report["checks"] if not c["passed"]}
    rows[0]["source"]["decision_id"] = None
    assert "valid_source_references" in failed_checks(rows)


def test_sessions_are_split_whole_and_in_order() -> None:
    sessions = [f"2025-06-{d:02d}" for d in range(1, 21)]
    splits = assign_splits(sessions, DatasetParameters())
    assert [splits[s] for s in sessions] == ["train"] * 14 + ["validation"] * 3 + ["test"] * 3


def test_small_datasets_still_get_every_split() -> None:
    splits = assign_splits(["a", "b", "c"], DatasetParameters())
    assert sorted(splits.values()) == ["test", "train", "validation"]
    with pytest.raises(DatasetBuildError):
        assign_splits(["a", "b"], DatasetParameters())


def test_parameters_must_leave_a_test_split() -> None:
    with pytest.raises(ValueError):
        DatasetParameters(train_ratio=0.8, validation_ratio=0.2)


def test_cleaner_reports_what_it_removes() -> None:
    rows = dataset()
    rows.append(copy.deepcopy(rows[0]))
    rows[1]["labels"]["decision"]["reason_codes"] = ["NO_MTZ_LEVELS"]
    rows[2]["features"]["market_context"]["close"] = None
    kept, report = clean(rows)
    assert len(kept) == 6
    assert report.removed == {"duplicate_timestamp": 1, "no_strategy_levels": 1, "missing_close": 1}
    kept, report = clean(dataset(), drop_without_levels=False)
    assert report.removed == {}


SIGNAL = datetime(2025, 6, 2, 4, 0, tzinfo=UTC)


def test_trades_are_matched_to_their_signal_candle() -> None:
    trade = {"entry_ts": SIGNAL + timedelta(minutes=5), "net_points": 4.0}
    assert trades_by_signal_time([trade]) == {SIGNAL: trade}


def decision(action: str, codes: list[str]) -> dict:
    return {"action": action, "reason_codes": codes}


def test_outcomes_for_taken_skipped_and_absent_setups() -> None:
    closes = [100.0, 101.0, 99.5]
    trade = {"net_points": -3.0, "exit_reason": "STOP_LOSS", "holding_seconds": 600}
    taken = outcome_labels(decision("BUY", ["OR_LONG"]), trade, closes, 0, (1, 2, 3))
    assert taken["setup_outcome"] == "taken_loss"
    assert taken["trade_result"] == "loss"
    assert taken["forward_return_points_1_bars"] == 1.0
    assert taken["forward_return_points_2_bars"] == -0.5
    assert taken["forward_return_points_3_bars"] is None  # never reaches into the next session

    ignored = outcome_labels(decision("BUY", ["OR_LONG"]), None, closes, 1, (1,))
    assert ignored["setup_outcome"] == "skipped"
    assert ignored["trade_taken"] is False
    away = outcome_labels(
        decision("HOLD", ["REVERSAL_NOT_AT_MTZ", "OR_LONG"]), None, closes, 1, (1,)
    )
    assert away["setup_outcome"] == "skipped"
    quiet = outcome_labels(decision("HOLD", ["NO_REVERSAL_SIGNAL"]), None, closes, 2, (1,))
    assert quiet["setup_outcome"] == "no_setup"
    assert quiet["forward_return_points_1_bars"] is None


def test_content_hash_ignores_the_version_label_only() -> None:
    rows = dataset()
    relabelled = copy.deepcopy(rows)
    for row in relabelled:
        row["dataset_version"] = "2.0"
    assert content_hash(rows) == content_hash(relabelled)
    relabelled[0]["features"]["market_context"]["close"] = 100.5
    assert content_hash(rows) != content_hash(relabelled)


@pytest.mark.parametrize("fmt", [ExportFormat.JSONL, ExportFormat.CSV, ExportFormat.PARQUET])
def test_exports_write_every_record(tmp_path: Path, fmt: ExportFormat) -> None:
    rows = dataset()
    path = tmp_path / f"train.{fmt.value}"
    sha = export_manager.write(rows, fmt, path, {"dataset": "test"})
    assert len(sha) == 64
    text = path.read_text(encoding="utf-8") if fmt != ExportFormat.PARQUET else None
    if fmt == ExportFormat.JSONL:
        assert len(text.splitlines()) == len(rows)
    elif fmt == ExportFormat.CSV:
        header = text.splitlines()[0]
        assert "features.market_context.close" in header
        assert "labels.decision.action" in header


def test_parquet_round_trip_restores_records(tmp_path: Path) -> None:
    rows = dataset()
    export_manager.write(rows, ExportFormat.PARQUET, tmp_path / "d.parquet", {})
    restored = export_manager.read_parquet(tmp_path / "d.parquet")
    assert restored == rows
    assert validate(restored)["passed"]
