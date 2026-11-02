"""Ingestion jobs and API on real PostgreSQL and Parquet, with a clearly labelled mock provider."""

import gzip
import json
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.data.ingestion.service import IngestionService, NoCandlesError
from app.data.storage.candle_store import CandleStore
from app.database.models import DataIngestionJob, DataProvider, Dataset, Instrument
from app.domain.candle import EXCHANGE_TZ
from app.domain.enums import DatasetStatus, JobStatus
from tests.support.mock_market_data import MockProvider

pytestmark = pytest.mark.integration

START = date(2025, 6, 2)
END = date(2025, 6, 30)
LATE = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session
    with Session(engine) as session:
        session.execute(delete(Dataset))
        session.execute(delete(DataIngestionJob))
        session.commit()


def make_job(db: Session, timeframe: str = "5m", start: date = START, end: date = END):
    job = DataIngestionJob(
        instrument_id=db.scalars(select(Instrument.id)).one(),
        provider_id=db.scalars(select(DataProvider.id).where(DataProvider.code == "dhan")).one(),
        timeframe=timeframe,
        start_date=start,
        end_date=end,
    )
    db.add(job)
    db.commit()
    return job


def service(
    db: Session,
    tmp_path: Path,
    provider: MockProvider,
    clock: Callable[[], datetime] = lambda: LATE,
) -> IngestionService:
    return IngestionService(db, provider, CandleStore(tmp_path), clock=clock)


def only_dataset(db: Session) -> Dataset:
    return db.scalars(select(Dataset)).one()


def test_job_downloads_in_chunks_and_publishes_a_ready_dataset(db: Session, tmp_path: Path) -> None:
    job = make_job(db)
    provider = MockProvider(chunk_days=10)
    service(db, tmp_path, provider).run(job.id)

    assert job.status == JobStatus.COMPLETED
    assert len(provider.calls) == 3
    dataset = only_dataset(db)
    assert dataset.status == DatasetStatus.READY
    assert dataset.version == 1
    assert dataset.ingestion_job_id == job.id
    assert dataset.row_count % 75 == 0
    assert dataset.quality_report["missing_candles"] == 0
    assert job.progress["dataset_id"] == str(dataset.id)
    assert job.progress["instrument"]["security_id"] == "mock-id"

    stored = CandleStore(tmp_path).query(dataset.manifest)
    assert stored.height == dataset.row_count
    CandleStore(tmp_path).verify(dataset.manifest)


def test_original_provider_payloads_are_preserved(db: Session, tmp_path: Path) -> None:
    job = make_job(db)
    service(db, tmp_path, MockProvider()).run(job.id)
    raw_files = list((tmp_path / "raw" / "dhan" / str(job.id)).glob("*.json.gz"))
    assert len(raw_files) == 3
    with gzip.open(raw_files[0], "rt") as handle:
        assert json.load(handle) == {"mock": True}


def test_failed_job_resumes_without_redownloading(db: Session, tmp_path: Path) -> None:
    job = make_job(db)
    provider = MockProvider()
    provider.fail_on_call = 2
    with pytest.raises(ConnectionError):
        service(db, tmp_path, provider).run(job.id)
    assert job.status == JobStatus.FAILED
    assert "mock provider failure" in (job.error or "")
    assert len(job.progress["completed_chunks"]) == 1
    assert db.scalars(select(Dataset)).first() is None

    job.status = JobStatus.PENDING
    job.error = None
    db.commit()
    provider.fail_on_call = None
    provider.calls.clear()
    service(db, tmp_path, provider).run(job.id)
    assert job.status == JobStatus.COMPLETED
    assert len(provider.calls) == 2
    assert only_dataset(db).quality_report["missing_candles"] == 0


def test_job_can_be_cancelled_between_chunks(db: Session, tmp_path: Path, engine: Engine) -> None:
    job = make_job(db)
    provider = MockProvider()

    def cancel_elsewhere() -> None:
        with Session(engine) as other:
            other.get_one(DataIngestionJob, job.id).status = JobStatus.CANCELLED
            other.commit()

    provider.on_call = cancel_elsewhere
    service(db, tmp_path, provider).run(job.id)
    assert job.status == JobStatus.CANCELLED
    assert len(provider.calls) == 1
    assert db.scalars(select(Dataset)).first() is None


def test_terminal_jobs_are_not_rerun(db: Session, tmp_path: Path) -> None:
    job = make_job(db)
    provider = MockProvider()
    service(db, tmp_path, provider).run(job.id)
    provider.calls.clear()
    service(db, tmp_path, provider).run(job.id)
    assert provider.calls == []


def test_identical_redownload_creates_no_new_version(db: Session, tmp_path: Path) -> None:
    service(db, tmp_path, MockProvider()).run(make_job(db).id)
    job = make_job(db)
    service(db, tmp_path, MockProvider()).run(job.id)
    assert only_dataset(db).version == 1
    assert job.progress["unchanged"] is True


def test_new_range_creates_a_merged_version_and_keeps_the_old_one(
    db: Session, tmp_path: Path
) -> None:
    service(db, tmp_path, MockProvider()).run(make_job(db).id)
    july = make_job(db, start=date(2025, 7, 1), end=date(2025, 7, 31))
    service(db, tmp_path, MockProvider()).run(july.id)

    first, second = db.scalars(select(Dataset).order_by(Dataset.version)).all()
    assert (first.version, second.version) == (1, 2)
    assert second.row_count > first.row_count
    assert second.manifest["based_on_dataset_id"] == str(first.id)
    store = CandleStore(tmp_path)
    assert store.query(first.manifest).height == first.row_count
    assert store.query(second.manifest).height == second.row_count
    assert second.end_date == date(2025, 7, 31)


def test_provider_revisions_are_counted_in_a_new_version(db: Session, tmp_path: Path) -> None:
    service(db, tmp_path, MockProvider()).run(make_job(db).id)
    service(db, tmp_path, MockProvider(price=200.0)).run(make_job(db).id)
    first, second = db.scalars(select(Dataset).order_by(Dataset.version)).all()
    assert second.quality_report["revised_candles"] == second.row_count
    assert CandleStore(tmp_path).query(first.manifest)["open"][0] == 100.0


def test_bars_still_forming_at_download_time_are_excluded(db: Session, tmp_path: Path) -> None:
    job = make_job(db, start=date(2025, 6, 16), end=date(2025, 6, 16))
    midday = datetime(2025, 6, 16, 9, 27, tzinfo=EXCHANGE_TZ)
    service(db, tmp_path, MockProvider(), clock=lambda: midday).run(job.id)
    dataset = only_dataset(db)
    # 09:15 and 09:20 have closed. 09:25 onward had not.
    assert dataset.row_count == 2
    assert dataset.quality_report["excluded_incomplete_candles"] == 73


def test_todays_daily_candle_is_excluded_until_the_close(db: Session, tmp_path: Path) -> None:
    job = make_job(db, "1d", date(2025, 6, 16), date(2025, 6, 17))
    midday = datetime(2025, 6, 17, 12, 0, tzinfo=EXCHANGE_TZ)
    service(db, tmp_path, MockProvider(), clock=lambda: midday).run(job.id)
    dataset = only_dataset(db)
    assert dataset.row_count == 1
    assert dataset.end_date == date(2025, 6, 16)


def test_empty_download_fails_rather_than_publishing_nothing(db: Session, tmp_path: Path) -> None:
    job = make_job(db)
    provider = MockProvider()
    provider.empty = True
    with pytest.raises(NoCandlesError):
        service(db, tmp_path, provider).run(job.id)
    assert job.status == JobStatus.FAILED
    assert db.scalars(select(Dataset)).first() is None


def test_reference_prints_outside_the_session_are_excluded_not_fatal(
    db: Session, tmp_path: Path
) -> None:
    class PrintsProvider(MockProvider):
        """Adds flat pre-open and closing-price candles, as Upstox did in 2022."""

        def get_historical_candles(self, instrument, timeframe, start, end):
            chunk = super().get_historical_candles(instrument, timeframe, start, end)
            extra = []
            for candle in chunk.candles:
                local = candle.timestamp.astimezone(EXCHANGE_TZ)
                if (local.hour, local.minute) == (9, 15):
                    extra.append(
                        candle.model_copy(
                            update={"timestamp": candle.timestamp - timedelta(minutes=5)}
                        )
                    )
                if (local.hour, local.minute) == (15, 25):
                    extra.append(
                        candle.model_copy(
                            update={"timestamp": candle.timestamp + timedelta(minutes=5)}
                        )
                    )
            chunk.candles.extend(extra)
            return chunk

    service(db, tmp_path, PrintsProvider()).run(make_job(db).id)
    dataset = only_dataset(db)
    sessions = dataset.row_count // 75
    assert dataset.status == DatasetStatus.READY
    assert dataset.row_count % 75 == 0
    report = dataset.quality_report
    assert report["outside_session_bars"] == 0
    assert report["excluded_outside_session_candles"] == 2 * sessions
    assert report["excluded_outside_session_by_time"] == {"09:10": sessions, "15:30": sessions}
    # The provider's original payload, including the prints, is still kept.
    assert list((tmp_path / "raw").rglob("*.json.gz"))


def test_critical_data_problems_mark_the_dataset_invalid(db: Session, tmp_path: Path) -> None:
    class BadProvider(MockProvider):
        def get_historical_candles(self, instrument, timeframe, start, end):
            chunk = super().get_historical_candles(instrument, timeframe, start, end)
            chunk.candles[0] = chunk.candles[0].model_copy(update={"high": 1.0})
            return chunk

    service(db, tmp_path, BadProvider()).run(make_job(db).id)
    dataset = only_dataset(db)
    assert dataset.status == DatasetStatus.INVALID
    assert dataset.quality_report["has_critical_issues"] is True
    assert dataset.quality_report["invalid_ohlc"] == 3
    assert dataset.row_count > 0


def test_invalid_versions_are_not_used_as_a_merge_base(db: Session, tmp_path: Path) -> None:
    class BadProvider(MockProvider):
        def get_historical_candles(self, instrument, timeframe, start, end):
            chunk = super().get_historical_candles(instrument, timeframe, start, end)
            chunk.candles[0] = chunk.candles[0].model_copy(update={"high": 1.0})
            return chunk

    service(db, tmp_path, BadProvider()).run(make_job(db).id)
    service(db, tmp_path, MockProvider()).run(make_job(db).id)
    latest = db.scalars(select(Dataset).order_by(Dataset.version.desc())).first()
    assert latest is not None
    assert latest.status == DatasetStatus.READY
    assert latest.manifest["based_on_dataset_id"] is None


# API


@pytest.fixture
def configured(client: TestClient, monkeypatch: pytest.MonkeyPatch, db: Session) -> TestClient:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "dhan_access_token", SecretStr("test-token"))
    return client


REQUEST = {
    "provider": "dhan",
    "timeframe": "5m",
    "start_date": "2025-06-02",
    "end_date": "2025-06-30",
}


def test_ingest_endpoint_queues_a_job(
    configured: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import market_data

    sent: list = []
    monkeypatch.setattr(
        market_data.run_ingestion, "apply_async", lambda args, retry: sent.append(args)
    )
    response = configured.post("/api/v1/market-data/ingest", json=REQUEST)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert sent == [[body["id"]]]
    assert configured.get(f"/api/v1/market-data/jobs/{body['id']}").json()["id"] == body["id"]
    assert body["id"] in [job["id"] for job in configured.get("/api/v1/market-data/jobs").json()]


def test_ingest_reports_an_unreachable_queue(
    configured: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import market_data

    def fail(args, retry):
        raise OperationalError("mock outage")

    monkeypatch.setattr(market_data.run_ingestion, "apply_async", fail)
    response = configured.post("/api/v1/market-data/ingest", json=REQUEST)
    assert response.status_code == 503
    job = configured.get("/api/v1/market-data/jobs").json()[0]
    assert job["status"] == "failed"


def test_ingest_requires_credentials(client: TestClient, db: Session) -> None:
    response = client.post("/api/v1/market-data/ingest", json=REQUEST)
    assert response.status_code == 409


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "other"},
        {"timeframe": "1m"},
        {"start_date": "2025-07-01"},
        {"end_date": "2999-01-01"},
        {"start_date": "2015-01-01"},
    ],
)
def test_ingest_validates_input(configured: TestClient, change: dict) -> None:
    response = configured.post("/api/v1/market-data/ingest", json={**REQUEST, **change})
    assert response.status_code == 422


def test_cancel_and_resume_enforce_job_state(
    configured: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import market_data

    monkeypatch.setattr(market_data.run_ingestion, "apply_async", lambda args, retry: None)
    job = make_job(db)
    url = f"/api/v1/market-data/jobs/{job.id}"
    assert configured.post(f"{url}/resume").status_code == 409
    assert configured.post(f"{url}/cancel").json()["status"] == "cancelled"
    assert configured.post(f"{url}/cancel").status_code == 409

    db.refresh(job)
    job.status = JobStatus.FAILED
    job.error = "mock"
    db.commit()
    resumed = configured.post(f"{url}/resume").json()
    assert resumed["status"] == "pending"
    assert resumed["error"] is None


def test_unknown_job_is_404(client: TestClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/market-data/jobs/{missing}").status_code == 404


def test_availability_and_health_show_the_latest_version(
    client: TestClient, db: Session, tmp_path: Path
) -> None:
    service(db, tmp_path, MockProvider()).run(make_job(db).id)
    service(db, tmp_path, MockProvider()).run(
        make_job(db, start=date(2025, 7, 1), end=date(2025, 7, 31)).id
    )
    datasets = client.get("/api/v1/market-data/availability").json()["datasets"]
    assert [row["version"] for row in datasets] == [2]
    assert "manifest" not in datasets[0]

    health = client.get("/api/v1/market-data/health").json()
    assert health["providers"][0]["code"] == "dhan"
    assert health["providers"][0]["configured"] is False
    assert health["datasets"][0]["quality_report"]["missing_candles"] == 0
    assert "test-token" not in str(health)

    assert len(client.get("/api/v1/market-data/datasets").json()) == 2
