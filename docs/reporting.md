# Reports

Code: `backend/app/reporting`. Reports are generated in the background for completed backtests and
saved under `DATA_ROOT/reports/<backtest id>/`, with their size and SHA-256 recorded.

## Categories

| Category | Contents | CSV and Parquet table |
| --- | --- | --- |
| `performance` | Metrics, units, Sharpe assumptions, monthly and daily performance, performance by condition | Metrics, one per row |
| `trades` | Every completed trade: prices, stop, target, exit reason, points, regime, indicators at entry and exit, execution assumptions | Trades |
| `decisions` | Every candle, including HOLD: OHLC, CPR, Camarilla, ADR, EMA 20, permissions, signals, decision, reason codes, explanation, position | Decisions |
| `market_behaviour` | Performance by trend, volatility, gap, session part, hour, weekday, ADR usage, CPR width and setup, with how each label is calculated | Condition rows |

## Formats

| Format | Contains | Metadata |
| --- | --- | --- |
| PDF | Every section, for reading | Details table on page 1; backtest ID and units in every footer |
| CSV | The category's main table, all rows and columns | `# key: value` lines before the header; read with `pandas.read_csv(path, comment="#")` |
| JSON | Every section and the metadata | `metadata` object |
| Parquet | The main table, all rows and columns | File key-value metadata, `report_metadata` |

JSONL is for AI datasets (Phase 7) and is not a report format.

In a PDF, tables longer than 500 rows show the first 500, and wide tables show selected columns.
Both cases are stated under the table, and the CSV and Parquet exports always contain everything.
Times are exchange time (IST).

## Metadata in every report

Backtest ID, strategy name, version and code hash, both dataset versions with content hashes,
generation time, instrument, exchange, timeframe, date range, execution method and settings, risk
settings, capital assumptions, input and result hashes, and the units notice:

> All results are theoretical NIFTY 50 spot index points. The spot index cannot be traded, so these
> figures are not rupee profits or losses.

## Endpoints

| Endpoint | Action |
| --- | --- |
| `POST /backtests/{id}/reports` | Queue reports: `{"categories": [...], "formats": [...]}`, one per combination |
| `GET /backtests/{id}/reports` | List reports and their status |
| `GET /backtests/{id}/reports/{report id}/download` | Download a completed report |

A report can only be requested for a completed backtest.
