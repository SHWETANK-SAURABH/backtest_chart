# NIFTY 50 Backtester

A historical backtesting, strategy analytics and AI dataset platform for the NIFTY 50 spot index.

NIFTY 50 spot is an index value and cannot be traded directly. Results are theoretical index
points, not rupee profit. This version does no live trading or order execution.

**Status:** see the [development checklist](docs/implementation-plan.md#development-checklist).

## Layout

| Path | Contents |
| --- | --- |
| `backend/app/api` | FastAPI routes and schemas |
| `backend/app/data` | Provider adapters, ingestion, Parquet storage, trading calendar |
| `backend/app/database` | SQLAlchemy models and sessions |
| `backend/alembic` | Database migrations |
| `backend/app/workers` | Celery tasks: ingestion and backtest queues |
| `frontend` | Next.js dashboard |
| `tests` | Unit, integration, parity, execution and dataset validation tests |
| `docs` | Plan and design documents |

## Run with Docker

```sh
cp .env.example .env    # then set a real POSTGRES_PASSWORD
docker compose up --build
```

- Dashboard: http://localhost:3000
- API documentation: http://localhost:8000/docs

Migrations run automatically before the API and workers start.

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

Paths are for Windows. On Linux and macOS use `backend/.venv/bin/python`. Without Redis, the
health endpoint correctly reports the system as degraded and background jobs cannot run.

## Dashboard

Pages for backtests, the interactive strategy chart, trades, historical data, strategies, reports
and AI datasets. See [docs/frontend.md](docs/frontend.md).

## Market data

See [docs/market-data.md](docs/market-data.md) for provider verification, storage and quality
checks. Downloads need `DHAN_ACCESS_TOKEN` in `.env`.

## Tests

```sh
backend/.venv/Scripts/python -m pytest
backend/.venv/Scripts/python -m pytest -m live_provider    # calls the real provider
```

Integration tests use real PostgreSQL: `TEST_DATABASE_URL` if set, otherwise the embedded server
in `.pgdata/`. They create and drop a separate `nifty_test` database.
