# Backtesting engine

Code: `backend/app/backtesting`, `backend/app/portfolio`, `backend/app/costs`.

## Units

NIFTY 50 spot cannot be traded, so every result is in **theoretical index points**. There is no
rupee profit and loss, and no brokerage, STT or exchange charges. `CostModel` is a separate module so
futures or options charges can be added later without touching the engine.

The initial capital in a backtest's settings is recorded for context only.

## Processing order

For each confirmed 5-minute candle, in time order:

1. Fill an entry left pending by the previous candle (next-open execution).
2. Check the open position's stop and target against this candle.
3. Act on this candle's strategy decision, which is only known at its close.
4. If this is the session's final candle, square off.

The strategy produces one decision at a time, and the engine never holds a reference to later
candles. Five sessions before the start date are evaluated to warm up indicators. No trades are
taken in that warm-up period, and its decisions are not stored.

## Execution settings

| Setting | Options | Default |
| --- | --- | --- |
| `method` | `next_open`, `signal_close` | `next_open` |
| `slippage_points` | 0 to 100 | 0 |
| `same_candle_policy` | `stop_first` | `stop_first` |

**`signal_close`** fills at the signal candle's close. That price is only known as the candle closes,
so this is an idealised assumption, and every trade records `signal_close_is_idealised: true`.

**`next_open`** fills at the next candle's open, which is the realistic comparison. If that open is
already beyond the stop or the target, the entry is skipped.

## Fills

| Event | Fill price | Time recorded |
| --- | --- | --- |
| Entry, signal close | Signal close, plus or minus slippage | Signal candle's close |
| Entry, next open | Next open, plus or minus slippage | That candle's open |
| Stop touched | Stop, minus or plus slippage | Close of that candle |
| Target touched | Target, no slippage (limit order) | Close of that candle |
| Candle opens beyond stop | That open, with slippage | That candle's open |
| Candle opens beyond target | That open | That candle's open |
| Session's final candle | Close, with slippage | Session close |

Intrabar exits are timestamped at the candle's close, the earliest moment the touch is certain.

**Stop and target in one candle.** Without lower-timeframe data, the order is unknown. The stop is
assumed to come first, and the trade is flagged `SAME_CANDLE_AMBIGUITY`.

## Positions and risk

- One position at a time. A signal while a position is open is ignored, in either direction.
- A new position may open at a candle's close after an exit earlier in that candle.
- No entries on a session's final candle, and no positions overnight.
- If data ends a session early, because its final candle is missing, the position is squared off at
  the last known close (`SESSION_END_MISSING_DATA`). An open position at the end of all data closes
  with `END_OF_DATA`.
- Optional limits: `max_trades_per_day` and `max_daily_loss_points` (realised, net). Both reset each
  session.

## Execution notes

Each stored decision records what execution did on that candle, in `trade_engine_state.execution_notes`:

| Note | Meaning |
| --- | --- |
| `ENTRY_PENDING_NEXT_OPEN` | Entry will fill at the next open |
| `ENTRY_SKIPPED_OPEN_BEYOND_STOP` / `_TARGET` | Next open had already passed a level |
| `PENDING_ENTRY_CANCELLED_NEW_SESSION` | Pending entry dropped at a session change |
| `SIGNAL_IGNORED_POSITION_OPEN` | One position at a time |
| `SIGNAL_IGNORED_SESSION_CLOSING` | Signal on the final candle |
| `SIGNAL_IGNORED_DAILY_TRADE_LIMIT` / `_LOSS_LIMIT` | Risk limit reached |
| `STOP_AND_TARGET_SAME_CANDLE_STOP_ASSUMED` | Conservative assumption applied |

## Reproducibility

- A backtest refers to exact dataset versions and an exact strategy version.
- `input_hash` covers the strategy version, its code hash and parameters, both dataset content
  hashes, the dates, and the settings.
- `result_hash` covers every trade and every decision's outcome.
- The same inputs give the same `result_hash`; a test runs a backtest twice to check this.
- A job is refused if the strategy code has changed since its version was registered, or if a
  dataset is invalid or its files have been modified.
- Once a backtest completes, its strategy version cannot be changed.
- `POST /backtests/{id}/rerun` queues a new run with identical inputs, and
  `GET /backtests/{id}/reproducibility` lists every run with the same input hash and whether their
  result hashes match. The results page shows this with a re-run button.

## Performance

On the development machine, the strategy and engine process a year of 5-minute candles (about
18,400) in 1.5 to 3.6 seconds. A complete one-year backtest, including saving every decision and
trade, takes about 14 seconds. `pytest -m performance` checks for regressions.

## Running a backtest

```sh
curl -X POST http://localhost:8000/api/v1/backtests -H "Content-Type: application/json" -d '{
  "strategy_version_id": "<id>",
  "start_date": "2026-01-01",
  "end_date": "2026-03-31",
  "execution": {"method": "next_open", "slippage_points": 0.5},
  "risk": {"max_trades_per_day": 3}
}'
```

The latest ready datasets are used unless `intraday_dataset_id` and `daily_dataset_id` are given.
Results are saved in one transaction when the run finishes, so a cancelled or failed run saves
nothing.
