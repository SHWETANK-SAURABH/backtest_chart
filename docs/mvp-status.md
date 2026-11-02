# MVP acceptance status

The prompt's 16 acceptance criteria, as of 2026-11-02.

| # | Criterion | Status | Evidence or what remains |
| --- | --- | --- | --- |
| 1 | Retrieve genuine NIFTY 50 spot data from a verified provider | **Pending: needs an Upstox (or Dhan) token** | Upstox and DhanHQ adapters built and verified against their docs; NIFTY 50 resolved from each provider's live instrument file (`NSE_INDEX\|Nifty 50`, Dhan ID 13); real candles not yet downloaded |
| 2 | Store historical 5-minute candles | Built | Versioned Parquet storage, tested; awaits real data |
| 3 | Retrieve supporting daily candles | Built | Same adapter; awaits real data |
| 4 | Execute the Pine Script strategy port | Done | `backend/app/strategy`; owner's entry rules in `docs/strategy.md` |
| 5 | Python calculations validated against TradingView | **Pending: needs TradingView exports** | Comparison test built and self-checked: `tests/strategy_parity` |
| 6 | Backtest a selected historical date range | Done | Backtest API and dashboard form |
| 7 | Simulate BUY, SELL and HOLD decisions | Done | Every candle gets a decision with reason codes |
| 8 | Record completed trades | Done | `trades` table, trade explorer |
| 9 | Generate performance metrics | Done | `docs/analytics.md` |
| 10 | Display an interactive historical chart | Done | `/backtests/{id}/chart` |
| 11 | Generate downloadable reports | Done | PDF, CSV, JSON, Parquet; `docs/reporting.md` |
| 12 | Record every candle-level decision | Done | `strategy_decisions` and `market_context` |
| 13 | Generate versioned AI-ready datasets | Done | `docs/ai-datasets.md` |
| 14 | Export datasets to JSONL, CSV and Parquet | Done | Nine files per version |
| 15 | Reproduce a backtest with the same inputs | Done | Re-run endpoint and dashboard card compare result hashes; tested end to end |
| 16 | Pass the relevant automated tests | Done for everything testable now | 329 pass; the TradingView comparison and real-data checks run once their inputs exist |

Everything except criteria 1 and 5 has been verified on synthetic data, which is labelled as such
and never written to the real database.

## Finishing the last two

**Criterion 1.** Put an Upstox access token in `.env` as `UPSTOX_ACCESS_TOKEN` (generate it at
https://account.upstox.com/developer/apps just before use). Then:

```sh
backend/.venv/Scripts/python -m pytest -m live_provider     # checks real candles against the quality rules
```

and download data from the Historical data page. Upstox 5-minute history starts in January 2022.
Anything the provider does differently from its documentation marks the dataset invalid rather
than being accepted silently. Dhan works the same way with `DHAN_ACCESS_TOKEN`.

**Criterion 5.** Export NIFTY 50 5-minute and daily charts from TradingView with the indicator
applied and "Number of Pivots" raised (steps in `tests/strategy_parity/fixtures/README.md`), place
them in that folder, then:

```sh
backend/.venv/Scripts/python -m pytest tests/strategy_parity
```

Signals are drawn as labels, which TradingView does not export, so they also need a visual
comparison on the chart.
