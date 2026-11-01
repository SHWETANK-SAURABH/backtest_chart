"""Shared fixtures.

Integration tests run against real PostgreSQL. TEST_DATABASE_URL selects a server; otherwise the
project-local embedded server is started. Each test session gets a fresh, migrated database.
"""

import os
import pathlib
from collections.abc import Iterator

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from alembic import command

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEST_DB = "nifty_test"


def alembic_config() -> Config:
    return Config(str(ROOT / "backend" / "alembic.ini"))


def _admin_url() -> tuple[str, object | None]:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        return url, None
    pgserver = pytest.importorskip("pgserver")
    server = pgserver.get_server(ROOT / ".pgdata", cleanup_mode="stop")
    return server.get_uri().replace("postgresql://", "postgresql+psycopg://"), server


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    admin_url, server = _admin_url()
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    head = admin_url.partition("?")[0].rpartition("/")[0]
    url = f"{head}/{TEST_DB}"

    os.environ["DATABASE_URL"] = url
    from app.core.config import get_settings
    from app.database.session import get_engine, get_session_factory

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    command.upgrade(alembic_config(), "head")
    yield url
    get_engine().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
    admin.dispose()
    if server is not None:
        server.cleanup()


@pytest.fixture
def engine(database_url: str) -> Engine:
    from app.database.session import get_engine

    return get_engine()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session whose changes are rolled back after the test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db
        transaction.rollback()


@pytest.fixture
def client(database_url: str) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
