# Market data

## Provider verification

Official documentation was read on 2026-11-01. "Not stated" means the pages read do not say.

| Check | DhanHQ (implemented) | Zerodha Kite Connect | Upstox |
| --- | --- | --- | --- |
| NIFTY 50 spot identifier | `13`, segment `IDX_I`, type `INDEX` (read from the live security master) | Not stated; look up in the instrument list | Not stated; look up in the instrument files |
| 5-minute candles | Yes | Yes (`5minute`) | Yes (`minutes/5`) |
| Daily candles | Yes | Yes (`day`) | Yes (`days/1`) |
| Maximum 5-minute range per request | 90 days | Not stated | 1 month |
| 5-minute history depth | Last 5 years | Not stated ("several years") | From January 2022 |
| Rate limit | 5 per second, 100,000 per day | 3 per second | 50 per second, 500 per minute, 2,000 per 30 minutes |
| Timestamps | Epoch; timezone not stated | ISO 8601 with offset | ISO 8601 with offset |
| Authentication | `access-token` header; 24-hour token | `Authorization` header; expires 6 AM next day | OAuth 2.0 bearer token; expiry not stated |
| Cost | Paid Data API plan; price not stated | Not stated | Not stated |

Dhan was implemented first because its documentation gives the longest stated 5-minute history
and the instrument can be verified from a public file. To add another provider, implement
`MarketDataProvider` in `backend/app/data/providers` and register it in `registry.py`.

## Open questions for the first live Dhan download

The documentation does not settle these. They are handled safely, and the first real download
answers them:

| Question | Handling |
| --- | --- |
| Are epoch values true UTC? | Parsed as UTC. If wrong, bars fall off the 5-minute grid or outside the session and the dataset is marked invalid |
| Does the index have meaningful volume? | Zero becomes null, because an index has no traded volume of its own. `rows_with_volume` in the quality report records what the provider sent |
| Is `interval` a string or an integer? | Sent as a string, following the documented example, although the field table says integer |
| Do daily candles sit at IST midnight? | The documented example does. Any other time is reported as misaligned |
| What is the daily range limit? | Not stated, so requests are limited to 365 days |

## Timestamp convention

- Candles are stamped at bar **open**, stored in UTC, and displayed in Asia/Kolkata.
- `trading_date` is the exchange-local date. It differs from the UTC date for daily candles.
- A 5-minute session runs 09:15 to 15:25 (bar opens), which is 75 bars.

## Storage

```
data/
  candles/symbol=NIFTY50/timeframe=5m/year=2025/month=06/dhan-<content hash>.parquet
  raw/dhan/<job id>/<start>_<end>.json.gz      original provider payloads, kept permanently
  staging/<job id>/                            completed chunks of unfinished jobs
```

Candle files are immutable and named by content. A `datasets` row is one version: a manifest of
files, a content hash and a quality report. A later download creates a new version that merges
with the latest ready one, leaving earlier versions intact, and identical data creates no new
version. The hash covers candle values only, not ingestion time.

If a provider revises a candle, the new version takes the new value and `revised_candles` records
the count.

## Quality checks

Checks report problems and never change or remove data.

| Check | Severity |
| --- | --- |
| Invalid OHLC relationships or non-positive prices | Critical |
| Duplicate timestamps, or repeats with conflicting values | Critical |
| Timestamps off the 5-minute grid, or daily candles not at IST midnight | Critical |
| Bars outside session hours on a scheduled date | Critical |
| Missing candles or whole sessions | Reported |
| Data on a date with no scheduled session | Reported, data kept |
| Dates beyond the calendar's holiday coverage | Reported |

A dataset with a critical issue is stored with status `invalid` and is not used as a merge base.
Backtests will refuse invalid datasets (Phase 4).

Two rows are excluded before publishing, and counted: bars still forming at download time, because
partial candles would leak unfinished data into a backtest, and rows outside the requested dates.

## Trading calendar

Sessions come from `pandas_market_calendars`, which has two known limits:

- Its NSE holidays stop after 2026. Later dates set `unverified_calendar_dates`, so their missing
  candle counts include holidays. Update `HOLIDAYS_POPULATED_THROUGH` when upgrading the library.
- It omits some special sessions, such as Saturday 2025-02-01. Such dates appear under
  `unscheduled_sessions`.

## Running a download

With Docker, use the API:

```sh
curl -X POST http://localhost:8000/api/v1/market-data/ingest \
  -H "Content-Type: application/json" \
  -d '{"provider":"dhan","timeframe":"5m","start_date":"2026-01-01","end_date":"2026-03-31"}'
```

Without Redis, run it in-process from `backend/`:

```sh
.venv/Scripts/python ../scripts/run_ingestion.py --timeframe 5m --start 2026-01-01 --end 2026-03-31
```

Failed jobs continue from their last completed chunk with `POST /market-data/jobs/{id}/resume`.

To check real data against every open question above, set `DHAN_ACCESS_TOKEN` and run:

```sh
backend/.venv/Scripts/python -m pytest -m live_provider
```
