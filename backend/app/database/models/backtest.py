"""Backtest jobs and everything a run produces.

Index levels and points use double precision so stored values round-trip exactly with the
engine's float64 calculations, which reproducibility checks depend on.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, uuid_pk
from app.domain.enums import JobStatus


class BacktestJob(TimestampMixin, Base):
    __tablename__ = "backtest_jobs"
    __table_args__ = (Index("ix_backtest_jobs_status", "status", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strategy_versions.id", ondelete="RESTRICT"), nullable=False
    )
    intraday_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False
    )
    daily_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    start_date: Mapped[date] = mapped_column(nullable=False)
    end_date: Mapped[date] = mapped_column(nullable=False)
    execution_method: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_settings: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    risk_settings: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    capital_assumptions: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    # Entry patterns and MTZ choice (StrategyOptions), applied over the version's parameters.
    strategy_options: Mapped[dict[str, Any]] = mapped_column(
        nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Hash of strategy version, dataset versions and settings, used to verify reproducibility.
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JobStatus.PENDING)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BacktestJobEvent(Base):
    __tablename__ = "backtest_job_events"
    __table_args__ = (Index("ix_backtest_job_events_job", "backtest_job_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    backtest_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("backtest_jobs.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StrategyDecision(Base):
    """One row per evaluated candle, including HOLD."""

    __tablename__ = "strategy_decisions"
    __table_args__ = (UniqueConstraint("backtest_job_id", "candle_ts"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    backtest_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("backtest_jobs.id", ondelete="CASCADE"), nullable=False
    )
    candle_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Double, nullable=False)
    high: Mapped[float] = mapped_column(Double, nullable=False)
    low: Mapped[float] = mapped_column(Double, nullable=False)
    close: Mapped[float] = mapped_column(Double, nullable=False)
    long_permission: Mapped[bool | None] = mapped_column()
    short_permission: Mapped[bool | None] = mapped_column()
    reversal_state: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    trade_engine_state: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    reason_codes: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    trade_opened: Mapped[bool] = mapped_column(nullable=False, default=False)
    position_closed: Mapped[bool] = mapped_column(nullable=False, default=False)
    position_state: Mapped[str] = mapped_column(String(16), nullable=False)


class MarketContext(Base):
    """Decision-time market context. Exact indicator fields are set by the Pine Script port."""

    __tablename__ = "market_context"

    decision_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("strategy_decisions.id", ondelete="CASCADE"), primary_key=True
    )
    cpr: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    camarilla: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    adr: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    adr_usage_percent: Mapped[float | None] = mapped_column(Double)
    ema20: Mapped[float | None] = mapped_column(Double)
    ema_direction: Mapped[str | None] = mapped_column(String(16))
    market_structure: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    market_regime: Mapped[str | None] = mapped_column(String(32))
    session_open: Mapped[float | None] = mapped_column(Double)
    condition_labels: Mapped[dict[str, Any]] = mapped_column(
        nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("backtest_job_id", "trade_number"),
        Index("ix_trades_job_entry", "backtest_job_id", "entry_ts"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    backtest_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("backtest_jobs.id", ondelete="CASCADE"), nullable=False
    )
    trade_number: Mapped[int] = mapped_column(nullable=False)
    trading_date: Mapped[date] = mapped_column(nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[float] = mapped_column(Double, nullable=False)
    exit_price: Mapped[float] = mapped_column(Double, nullable=False)
    stop_loss: Mapped[float | None] = mapped_column(Double)
    target: Mapped[float | None] = mapped_column(Double)
    exit_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    holding_seconds: Mapped[int] = mapped_column(nullable=False)
    gross_points: Mapped[float] = mapped_column(Double, nullable=False)
    cost_points: Mapped[float] = mapped_column(Double, nullable=False, default=0.0)
    net_points: Mapped[float] = mapped_column(Double, nullable=False)
    market_regime: Mapped[str | None] = mapped_column(String(32))
    indicators_at_entry: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    indicators_at_exit: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    decision_reason: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    execution_assumptions: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)


class BacktestMetrics(Base):
    __tablename__ = "backtest_metrics"

    backtest_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("backtest_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    total_trades: Mapped[int] = mapped_column(nullable=False)
    winning_trades: Mapped[int] = mapped_column(nullable=False)
    losing_trades: Mapped[int] = mapped_column(nullable=False)
    gross_profit_points: Mapped[float] = mapped_column(Double, nullable=False)
    gross_loss_points: Mapped[float] = mapped_column(Double, nullable=False)
    net_points: Mapped[float] = mapped_column(Double, nullable=False)
    # Nullable where the value is undefined, e.g. profit factor with no losing trades.
    win_rate: Mapped[float | None] = mapped_column(Double)
    profit_factor: Mapped[float | None] = mapped_column(Double)
    expectancy_points: Mapped[float | None] = mapped_column(Double)
    average_trade_points: Mapped[float | None] = mapped_column(Double)
    average_win_points: Mapped[float | None] = mapped_column(Double)
    average_loss_points: Mapped[float | None] = mapped_column(Double)
    max_drawdown_points: Mapped[float | None] = mapped_column(Double)
    average_holding_seconds: Mapped[float | None] = mapped_column(Double)
    max_consecutive_wins: Mapped[int] = mapped_column(nullable=False)
    max_consecutive_losses: Mapped[int] = mapped_column(nullable=False)
    sharpe_ratio: Mapped[float | None] = mapped_column(Double)
    sharpe_assumptions: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    by_market_condition: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    unit_summary: Mapped[dict[str, Any]] = mapped_column(
        nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class EquityCurvePoint(Base):
    __tablename__ = "equity_curve"
    __table_args__ = (UniqueConstraint("backtest_job_id", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    backtest_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("backtest_jobs.id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cumulative_points: Mapped[float] = mapped_column(Double, nullable=False)
    drawdown_points: Mapped[float] = mapped_column(Double, nullable=False)


class DailyPerformance(Base):
    __tablename__ = "daily_performance"
    __table_args__ = (UniqueConstraint("backtest_job_id", "trading_date"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    backtest_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("backtest_jobs.id", ondelete="CASCADE"), nullable=False
    )
    trading_date: Mapped[date] = mapped_column(nullable=False)
    trades: Mapped[int] = mapped_column(nullable=False)
    wins: Mapped[int] = mapped_column(nullable=False)
    losses: Mapped[int] = mapped_column(nullable=False)
    net_points: Mapped[float] = mapped_column(Double, nullable=False)
