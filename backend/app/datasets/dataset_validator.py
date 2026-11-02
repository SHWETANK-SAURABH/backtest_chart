"""Checks a dataset before it is published, and again on request from its exported files."""

from collections import Counter
from collections.abc import Callable, Iterable
from itertools import pairwise
from typing import Any

from app.datasets.schema import (
    ACTIONS,
    DECISION_LABELS,
    MARKET_CONTEXT_FEATURES,
    OUTCOME_LABELS,
    SETUP_OUTCOMES,
    SPLITS,
    STRATEGY_STATE_FEATURES,
    TRADE_RESULTS,
)

REQUIRED_META = ("timestamp", "trading_date", "split", "strategy_version", "dataset_version")


def _check(name: str, problems: list[str]) -> dict[str, Any]:
    return {
        "check": name,
        "passed": not problems,
        "problems": problems[:20],
        "count": len(problems),
    }


def validate(
    records: list[dict[str, Any]],
    known_decision_ids: Callable[[Iterable[int]], set[int]] | None = None,
) -> dict[str, Any]:
    checks = []

    missing = [
        f"{r.get('timestamp')}: {key}"
        for r in records
        for key in REQUIRED_META
        if r.get(key) in (None, "")
    ]
    missing += [
        f"{r['timestamp']}: label {key}"
        for r in records
        for key in DECISION_LABELS + OUTCOME_LABELS
        if key not in r["labels"]["decision"] and key not in r["labels"]["outcome"]
    ]
    checks.append(_check("missing_fields", missing))

    # Read with .get throughout: a malformed record must be reported, not crash the validator.
    invalid = []
    for r in records:
        decision, outcome = r["labels"]["decision"], r["labels"]["outcome"]
        if decision.get("action") not in ACTIONS:
            invalid.append(f"{r['timestamp']}: action {decision.get('action')}")
        if outcome.get("trade_result") not in TRADE_RESULTS:
            invalid.append(f"{r['timestamp']}: trade_result {outcome.get('trade_result')}")
        if outcome.get("setup_outcome") not in SETUP_OUTCOMES:
            invalid.append(f"{r['timestamp']}: setup_outcome {outcome.get('setup_outcome')}")
        if outcome.get("trade_taken") != (outcome.get("trade_result") is not None):
            invalid.append(f"{r['timestamp']}: trade_taken disagrees with trade_result")
        if r.get("split") not in SPLITS:
            invalid.append(f"{r['timestamp']}: split {r.get('split')}")
    checks.append(_check("invalid_labels", invalid))

    counts = Counter(r["timestamp"] for r in records)
    checks.append(_check("duplicate_records", sorted(t for t, n in counts.items() if n > 1)))

    # Features must be exactly the decision-time whitelist: nothing extra can hide in them.
    leakage = []
    allowed = {
        "market_context": set(MARKET_CONTEXT_FEATURES),
        "strategy_state": set(STRATEGY_STATE_FEATURES),
    }
    label_names = set(DECISION_LABELS) | set(OUTCOME_LABELS)
    for r in records:
        for group, names in r["features"].items():
            unexpected = set(names) - allowed.get(group, set())
            if unexpected:
                leakage.append(f"{r['timestamp']}: {group} has {sorted(unexpected)}")
            if set(names) & label_names:
                leakage.append(f"{r['timestamp']}: {group} contains label fields")
        if any(
            key.startswith("forward_return") for group in r["features"].values() for key in group
        ):
            leakage.append(f"{r['timestamp']}: forward return in features")
    checks.append(_check("future_feature_leakage", leakage))

    split_problems = []
    order = {split: i for i, split in enumerate(SPLITS)}
    by_split: dict[str, list[dict[str, Any]]] = {s: [] for s in SPLITS}
    for r in records:
        by_split.setdefault(r["split"], []).append(r)
    for split, rows in by_split.items():
        ts = [r["timestamp"] for r in rows]
        if ts != sorted(ts):
            split_problems.append(f"{split} is not in chronological order")
    present = [s for s in SPLITS if by_split.get(s)]
    for earlier, later in pairwise(present):
        if max(r["timestamp"] for r in by_split[earlier]) >= min(
            r["timestamp"] for r in by_split[later]
        ):
            split_problems.append(f"{earlier} overlaps {later} in time")
        shared = {r["trading_date"] for r in by_split[earlier]} & {
            r["trading_date"] for r in by_split[later]
        }
        if shared:
            split_problems.append(f"{earlier} and {later} share sessions {sorted(shared)[:3]}")
    if records and [order.get(r["split"], -1) for r in records] != sorted(
        order.get(r["split"], -1) for r in records
    ):
        split_problems.append("records are not ordered train, validation, test")
    checks.append(_check("chronological_splits", split_problems))

    versions = {(r.get("strategy_version"), r.get("strategy_code_hash")) for r in records}
    checks.append(
        _check(
            "consistent_strategy_version",
            [] if len(versions) <= 1 else [f"found {sorted(map(str, versions))}"],
        )
    )

    reference_problems = [
        f"{r['timestamp']}: no decision id"
        for r in records
        if not r.get("source", {}).get("decision_id")
    ]
    if known_decision_ids is not None and records:
        ids = {
            r["source"]["decision_id"] for r in records if r.get("source", {}).get("decision_id")
        }
        missing_ids = ids - known_decision_ids(ids)
        reference_problems += [f"decision {i} does not exist" for i in sorted(missing_ids)]
        if len({r["source"].get("backtest_id") for r in records}) > 1:
            reference_problems.append("records come from more than one backtest")
    checks.append(_check("valid_source_references", reference_problems))

    return {"passed": all(c["passed"] for c in checks), "records": len(records), "checks": checks}
