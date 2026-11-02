# Implementation plan

## Starting point

Inspected at project start (2026-11-01):

| Item | Finding |
| --- | --- |
| Existing code | None |
| Pine Script source | Supplied on 2026-11-02, kept outside version control |
| Provider credentials | None configured |
| Historical NIFTY 50 data | None |

## Architecture

A modular monolith with three independently scalable processes: API server, ingestion worker and
backtest worker. Each worker consumes its own Celery queue.

```
Next.js dashboard -> FastAPI -> PostgreSQL (configuration, jobs, results, provenance)
                       |
                     Redis -> ingestion worker -> provider adapters -> Parquet
                           -> backtest worker  -> strategy -> engine -> results
                                                  DuckDB queries over Parquet
```

Module dependencies point one way. The strategy module knows nothing about execution, the backtest
engine knows nothing about reports, and AI dataset generation reads stored results rather than
hooking into the engine.

### Decisions

| Decision | Reason |
| --- | --- |
| Synchronous SQLAlchemy with psycopg | Same data layer for the API and Celery. Heavy work runs in workers |
| Double precision for prices and points | Stored values round-trip exactly with float64 engine results, so reproducibility hashes can be checked |
| Timestamps stored in UTC, displayed in Asia/Kolkata | One internal convention, plus a stored exchange-local trading date |
| Immutable, content-addressed candle files | A dataset version always resolves to the same bytes, even after later downloads |
| Strategy version immutability in a database trigger | Holds regardless of which code path attempts the change |
| Strategy-specific values stored as JSONB | Exact indicator fields come from the Pine Script and are not assumed here |

## Database schema

Created by migrations in `backend/alembic/versions`. Models are in `backend/app/database/models`.

| Area | Tables |
| --- | --- |
| Market data | `instruments`, `data_providers`, `datasets`, `data_ingestion_jobs` |
| Strategy | `strategies`, `strategy_versions` |
| Backtest | `backtest_jobs`, `backtest_job_events`, `trades`, `strategy_decisions`, `market_context`, `backtest_metrics`, `equity_curve`, `daily_performance` |
| Reporting | `generated_reports` |
| AI datasets | `ai_datasets`, `ai_dataset_versions`, `dataset_exports` |

`backtest_jobs` references the exact strategy version and the 5-minute and daily dataset versions,
and stores execution settings and an input hash. Together these identify what produced each result.
Referenced versions cannot be deleted (`ON DELETE RESTRICT`).

## API structure

All routes are under `/api/v1`.

| Group | Endpoints | Phase |
| --- | --- | --- |
| System | `GET /health`, `GET /overview` | 1 |
| Instruments | `GET /instruments` | 1 |
| Market data | `GET /market-data/availability`, `/datasets`, `/health`, `POST /market-data/ingest`, `GET /market-data/jobs`, `GET /market-data/jobs/{id}`, `POST /market-data/jobs/{id}/cancel`, `/resume` | 2 |
| Strategies | `GET`/`POST /strategies`, `GET /strategies/{id}`, `POST /strategies/{id}/versions` (Pine source stored, not returned) | 3 |
| Backtests | `POST`/`GET /backtests`, `GET /backtests/{id}` (with events and trade count), `POST /backtests/{id}/cancel` | 4 |
| Analytics | `GET /backtests/{id}/metrics`, `/trades`, `/equity`, `/daily`, `/decisions` | 5 |
| Reports | `POST`/`GET /backtests/{id}/reports` | 6 |
| AI datasets | `POST /ai-datasets/generate`, `GET /ai-datasets`, `GET /ai-datasets/{id}`, `/validate`, `/exports` | 7 |

## Development checklist

- [x] Phase 1: Foundation
- [ ] Phase 2: Historical data (built and tested with mocks; awaiting a first real download, which needs a Dhan Data API token)
- [ ] Phase 3: Strategy implementation (built and tested; accuracy against TradingView awaits exports, see [strategy.md](strategy.md))
- [x] Phase 4: Backtesting engine ([backtesting.md](backtesting.md); not yet run on real data)
- [ ] Phase 5: Analytics
- [ ] Phase 6: Reporting
- [ ] Phase 7: AI dataset pipeline
- [ ] Phase 8: Frontend completion
- [ ] Phase 9: Quality assurance

## Known limitations

- No real candles have been downloaded yet. See the open questions in
  [market-data.md](market-data.md).
