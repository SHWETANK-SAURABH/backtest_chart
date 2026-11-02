# NIFTY 50 Backtester

A historical backtesting, strategy analytics and AI dataset platform for the NIFTY 50 spot index.

NIFTY 50 spot is an index value and cannot be traded directly, so results are theoretical index
points, not rupee profit. There is no live trading or order execution.

**Status:** all nine phases built. Two acceptance criteria wait on inputs: a real data download
(needs an Upstox token) and the TradingView comparison (needs exports). See
[docs/mvp-status.md](docs/mvp-status.md).

## What it does

1. Downloads NIFTY 50 5-minute and daily candles from Upstox or DhanHQ into immutable, versioned datasets with
   quality reports.
2. Runs the owner's Pine Script strategy, ported to Python, on every candle: BUY, SELL or HOLD, with
   the reasons.
3. Backtests chronologically with next-open or signal-close fills, slippage, stops, targets and
   end-of-day square-off.
4. Calculates performance, drawdown, daily and monthly results, and results by market condition.
5. Produces reports in PDF, CSV, JSON and Parquet.
6. Builds versioned AI training datasets with leakage checks and chronological splits.
7. Shows it all in a dashboard, including an interactive strategy chart.

## Architecture

```
Next.js dashboard -> FastAPI -> PostgreSQL (jobs, results, versions, provenance)
                       |
                     Redis -> ingestion worker -> Upstox or DhanHQ -> Parquet (DuckDB queries)
                           -> backtest worker  -> strategy -> engine -> analytics
                                                  reports, AI datasets
```

| Path | Contents |
| --- | --- |
| `backend/app/data` | Provider adapters, ingestion, Parquet storage, NSE calendar, quality checks |
| `backend/app/strategy` | The Pine Script port and the owner's entry rules |
| `backend/app/backtesting`, `portfolio`, `costs` | Execution engine, positions and risk, cost models |
| `backend/app/analytics` | Metrics and market condition labels |
| `backend/app/reporting` | Report content and exporters |
| `backend/app/datasets` | AI dataset pipeline |
| `backend/app/api` | REST endpoints under `/api/v1` |
| `frontend` | Dashboard |
| `tests` | Unit, integration, execution, strategy parity, dataset validation, performance |

## Run with Docker

```sh
cp .env.example .env    # set POSTGRES_PASSWORD, and UPSTOX_ACCESS_TOKEN (or DHAN_ACCESS_TOKEN) to download data
docker compose up --build
```

- Dashboard: http://localhost:3000
- API documentation: http://localhost:8000/docs

Migrations run automatically before the API and workers start.

## First use

1. Download 5-minute and daily data on the Historical data page. Daily data needs to start at least
   two weeks before the 5-minute data, and a year earlier for yearly levels.
2. Register the strategy version with the API running:
   ```sh
   cd backend
   .venv/Scripts/python ../scripts/register_strategy.py --pine ../prompt/strategy.pine --version 1.0.0
   ```
3. Run a backtest from New backtest, then explore results, the chart, trades, reports and datasets.

## Run without Docker

Requires Python 3.12+ and Node 24.

```sh
python3.12 -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -e "backend[dev]"

# Prints a database URL. Keep it running, and set DATABASE_URL to that value for later commands.
backend/.venv/Scripts/python scripts/dev_postgres.py

cd backend
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:app --port 8000

cd frontend
npm install
npm run dev
```

Paths are for Windows; on Linux and macOS use `backend/.venv/bin/python`. Without Redis, background
jobs cannot run; `scripts/run_ingestion.py` downloads data in-process instead.

## Tests

```sh
backend/.venv/Scripts/python -m pytest                       # 329 tests
backend/.venv/Scripts/python -m pytest -m performance        # throughput on a year of candles
backend/.venv/Scripts/python -m pytest -m live_provider      # real provider checks; needs a token
backend/.venv/Scripts/python -m pytest tests/strategy_parity # TradingView comparison; needs exports
```

Integration tests use real PostgreSQL: `TEST_DATABASE_URL` if set, otherwise an embedded server in
`.pgdata/`. Tests use synthetic candles, labelled as such, and never the real database.

## Documentation

| Document | Covers |
| --- | --- |
| [mvp-status.md](docs/mvp-status.md) | Acceptance criteria and how to finish the last two |
| [implementation-plan.md](docs/implementation-plan.md) | Architecture, schema, API, checklist |
| [market-data.md](docs/market-data.md) | Provider verification, storage, quality checks, calendar |
| [strategy.md](docs/strategy.md) | Every strategy rule, its source, and every implementation choice |
| [backtesting.md](docs/backtesting.md) | Execution rules, fills, risk, reproducibility |
| [analytics.md](docs/analytics.md) | Metric definitions, Sharpe assumptions, market condition labels |
| [reporting.md](docs/reporting.md) | Report categories and formats |
| [ai-datasets.md](docs/ai-datasets.md) | Dataset layers, features, labels, validation, training guidance |
| [frontend.md](docs/frontend.md) | Dashboard pages |
