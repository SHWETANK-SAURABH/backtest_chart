"""Download candles in this process, without Redis or a Celery worker.

Run from backend/ with DATABASE_URL, DATA_ROOT and DHAN_ACCESS_TOKEN set, for example:

    python ../scripts/run_ingestion.py --timeframe 5m --start 2026-01-01 --end 2026-03-31
"""

import argparse
import json
from datetime import date

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.data.providers.registry import build_provider
from app.database.models import DataIngestionJob, DataProvider, Dataset, Instrument
from app.database.session import get_session_factory
from app.domain.candle import NIFTY50
from app.workers.ingestion import run_ingestion_job


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="dhan")
    parser.add_argument("--timeframe", choices=["5m", "1d"], required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    connection = build_provider(args.provider, settings).validate_connection()
    print(f"Provider: {connection.detail}")
    if not connection.connected:
        raise SystemExit(1)

    with get_session_factory()() as session:
        job = DataIngestionJob(
            instrument_id=session.scalars(
                select(Instrument.id).where(Instrument.symbol == NIFTY50)
            ).one(),
            provider_id=session.scalars(
                select(DataProvider.id).where(DataProvider.code == args.provider)
            ).one(),
            timeframe=args.timeframe,
            start_date=args.start,
            end_date=args.end,
        )
        session.add(job)
        session.commit()
        job_id = job.id

    run_ingestion_job(str(job_id))

    with get_session_factory()() as session:
        job = session.get_one(DataIngestionJob, job_id)
        dataset = session.get_one(Dataset, job.progress["dataset_id"])
        print(f"Dataset version {dataset.version}: {dataset.status}, {dataset.row_count} rows")
        print(json.dumps(dataset.quality_report, indent=2))


if __name__ == "__main__":
    main()
