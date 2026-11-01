"""Alembic environment. The database URL always comes from application settings."""

from sqlalchemy import create_engine

from alembic import context
from app.core.config import get_settings
from app.database import models  # noqa: F401
from app.database.base import Base

target_metadata = Base.metadata


def run_migrations() -> None:
    url = get_settings().database_url
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations()
