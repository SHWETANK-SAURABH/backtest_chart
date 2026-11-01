"""Strategies and their immutable versions."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, uuid_pk


class Strategy(TimestampMixin, Base):
    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class StrategyVersion(TimestampMixin, Base):
    """Immutable once used by a completed backtest (enforced by a database trigger)."""

    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_id", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    pine_source: Mapped[str | None] = mapped_column(Text)
    pine_source_reference: Mapped[str | None] = mapped_column(String(512))
    python_implementation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    indicator_settings: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    execution_settings: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    change_description: Mapped[str | None] = mapped_column(Text)
