# AI datasets

Code: `backend/app/datasets`. Datasets are built from a completed backtest's stored results. The
module never calls the backtesting engine, so either can change without the other.

| Module | Role |
| --- | --- |
| `dataset_builder.py` | Orchestrates the steps below for one dataset version |
| `feature_builder.py` | Decision-time features from one stored decision |
| `data_labeler.py` | Decision labels and outcome labels |
| `data_cleaner.py` | Removes unusable records and reports every removal |
| `dataset_validator.py` | Checks run before publishing, and again on request from the files |
| `export_manager.py` | JSONL, CSV and Parquet output |
| `dataset_version_manager.py` | Dataset names, versions and content hashes |
| `schema.py` | The fixed list of features and labels |

## Layers

| Layer | Contents | Where |
| --- | --- | --- |
| 1. Raw market data | Candles, provider payloads, quality reports | Immutable candle datasets, referenced by content hash in every record (`data_version`) |
| 2. Structured strategy data | Every candle's decision, context, permissions, signals; trades | The backtest's stored results |
| 3. AI-ready datasets | Cleaned records with features, labels, versions and splits | `DATA_ROOT/ai_datasets/<dataset id>/<version>/` |

## Record format

One record per candle, including HOLD:

```json
{
  "timestamp": "2025-06-09T10:30:00+05:30",
  "trading_date": "2025-06-09",
  "instrument": "NIFTY50",
  "timeframe": "5m",
  "features": {
    "market_context": {"close": 22012.1, "price_vs_ema20": "above", "cpr_position": "above_tc",
                       "adr_usage_percent": 85.2, "market_regime": "trending_normal_volatility", "...": "..."},
    "strategy_state": {"long_permission": true, "short_permission": false,
                       "reversal_signals": ["OR_long"], "reversal_setup": true, "position_before": "flat", "...": "..."}
  },
  "labels": {
    "decision": {"action": "BUY", "reason_codes": ["OR_LONG", "AT_DAILY_MTZ", "TARGET_WEEKLY_MTZ"]},
    "outcome": {"trade_taken": true, "trade_net_points": -18.4, "trade_result": "loss",
                "exit_reason": "STOP_LOSS", "holding_seconds": 3600, "setup_outcome": "taken_loss",
                "forward_return_points_1_bars": 3.2, "forward_return_points_3_bars": -6.1,
                "forward_return_points_6_bars": null}
  },
  "strategy_version": "1.0.0",
  "strategy_code_hash": "...",
  "dataset_version": "1.0",
  "data_version": {"intraday": "...", "daily": "..."},
  "source": {"backtest_id": "...", "decision_id": 123},
  "split": "train"
}
```

The values above illustrate the format only. The complete feature list is in `schema.py`.

### Features and labels

**Features** are known when the decision is made: price relative to EMA 20 and the CPR, distances to
the daily and weekly MTZ, CPR width and relationships, Camarilla relationship, ADR usage, the
decision-time condition labels, the trade direction panel's state, which reversal candles confirmed,
and the position held before the candle.

**Labels** come in two kinds:

- `decision` is what the strategy did on that candle. It is known at decision time, but it is the
  target, not an input.
- `outcome` is only known later: whether a trade was taken, its result, and forward price changes.

**Outcome labels must never be used as inputs.** The validator enforces this by rejecting any feature
outside the fixed list in `schema.py`.

`setup_outcome` covers the cases the prompt asks for:

| Value | Meaning |
| --- | --- |
| `taken_win`, `taken_loss`, `taken_breakeven` | A trade was entered from this candle's signal |
| `skipped` | A setup appeared but was not traded: away from an MTZ, no target, invalid stop, conflicting signals, or ignored by execution |
| `no_setup` | No reversal candle |

Forward returns are close-to-close changes after 1, 3 and 6 candles (configurable). They never reach
into the next session, and are null where the session ends first.

No confidence scores are produced.

## Cleaning

Removed and counted in the validation report: duplicate timestamps, records without a close, and, by
default, candles evaluated before enough daily history existed for levels (`NO_MTZ_LEVELS`). Values
are never changed.

## Splits

Whole sessions in time order: the earliest 70% to `train`, the next 15% to `validation`, the rest to
`test` (configurable). A session is never divided, and labels never cross sessions, so no label can
overlap two splits. At least three sessions are needed.

## Validation

| Check | Fails when |
| --- | --- |
| `missing_fields` | A required field or label is absent or empty |
| `invalid_labels` | An action, result, setup outcome or split is not an allowed value, or `trade_taken` disagrees with `trade_result` |
| `duplicate_records` | Two records share a timestamp |
| `future_feature_leakage` | A feature is not on the decision-time list, matches a label name, or is a forward return |
| `chronological_splits` | A split is out of order, overlaps the next in time, or shares a session with it |
| `consistent_strategy_version` | Records come from more than one strategy version or code hash |
| `valid_source_references` | A record has no decision id, the id does not exist, or records mix backtests |

A dataset that fails validation is stored with its report and status `failed`, and nothing is
exported. `GET /ai-datasets/{id}/validate` re-checks a published version: file checksums, then every
rule on the records read back from Parquet, then the content hash.

## Versions and reproducibility

Each generation creates a new version, numbered `1.0`, `2.0`, and so on. It records its backtest and
parameters. The content hash ignores the version label, so the same backtest and parameters give the
same hash, and a test checks this.

## Exports

Each split is exported three ways:

| Format | Shape |
| --- | --- |
| JSONL | One nested record per line, as above |
| CSV | Flattened: `features.market_context.close`, `labels.decision.action`; lists as JSON text |
| Parquet | Flattened like CSV, with typed columns; dataset metadata in the file's key-value metadata |

## Preparing the data for training

These files are structured data, not ready-made training sets. JSONL is not automatically suitable
for fine-tuning a language model. Typical transformations:

| Goal | Inputs | Target | Notes |
| --- | --- | --- | --- |
| Imitate the strategy (classification) | `features.*` | `labels.decision.action` | Expect HOLD to dominate (about 98% of candles in the synthetic test run), so rebalance or weight classes, and evaluate per class |
| Predict trade quality | `features.*` of taken setups only | `labels.outcome.trade_result` or `trade_net_points` | Filter `setup_outcome` to `taken_*`; few rows per year, so check sample size |
| Forecast short-term moves | `features.*` | A `forward_return_points_*` label | Drop rows where the label is null |
| Fine-tune a language model | Features rendered as text in a prompt | Decision and reason codes rendered as the response | Build prompt and response pairs in the target model's chat format. Never put outcome labels in the prompt |
| Explain decisions | Features plus decision | The stored explanation text, from the decision report | The explanation comes only from the reason codes the strategy produced |

Always keep the provided splits: random shuffling across time leaks future market conditions into
training. Index points are theoretical; results in rupees need a futures or options model first.

## Endpoints

| Endpoint | Returns |
| --- | --- |
| `POST /ai-datasets/generate` | Queues a new version: `{"name", "backtest_id", "parameters": {...}}` |
| `GET /ai-datasets` | All versions, with record counts, label distribution and split statistics |
| `GET /ai-datasets/{id}` | One version |
| `GET /ai-datasets/{id}/validate` | A fresh validation of the published files |
| `GET /ai-datasets/{id}/exports` | The nine export files |
| `GET /ai-datasets/{id}/exports/{export id}/download` | One file |
