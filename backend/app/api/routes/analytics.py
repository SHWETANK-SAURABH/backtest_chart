"""Results of a completed backtest."""

import uuid
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.analytics.metrics import PeriodPerformance, monthly_performance
from app.api.schemas import (
    DailyPerformanceResponse,
    DecisionPage,
    DecisionResponse,
    EquityPointResponse,
    MetricsResponse,
    TradePage,
    TradeResponse,
)
from app.database.models import (
    BacktestJob,
    BacktestMetrics,
    DailyPerformance,
    EquityCurvePoint,
    MarketContext,
    StrategyDecision,
    Trade,
)
from app.database.session import get_session
from app.domain.candle import EXCHANGE_TZ
from app.domain.enums import JobStatus

router = APIRouter(prefix="/backtests/{job_id}", tags=["backtest-analytics"])
SessionDep = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=5000)]
Offset = Annotated[int, Query(ge=0)]


def _completed(session: Session, job_id: uuid.UUID) -> BacktestJob:
    job = session.get(BacktestJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backtest not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Backtest is {job.status}, not completed")
    return job


def _count(session: Session, query: Select[*tuple[Any, ...]]) -> int:
    return session.scalar(select(func.count()).select_from(query.subquery())) or 0


def _exchange_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, EXCHANGE_TZ)


@router.get("/metrics")
def metrics(job_id: uuid.UUID, session: SessionDep) -> MetricsResponse:
    job = _completed(session, job_id)
    row = session.get_one(BacktestMetrics, job.id)
    return MetricsResponse.model_validate(row)


@router.get("/trades")
def trades(
    job_id: uuid.UUID,
    session: SessionDep,
    side: Literal["long", "short"] | None = None,
    outcome: Literal["win", "loss", "breakeven"] | None = None,
    exit_reason: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: Limit = 500,
    offset: Offset = 0,
) -> TradePage:
    job = _completed(session, job_id)
    query = select(Trade).where(Trade.backtest_job_id == job.id)
    if side:
        query = query.where(Trade.side == side)
    if outcome == "win":
        query = query.where(Trade.net_points > 0)
    elif outcome == "loss":
        query = query.where(Trade.net_points < 0)
    elif outcome == "breakeven":
        query = query.where(Trade.net_points == 0)
    if exit_reason:
        query = query.where(Trade.exit_reason == exit_reason)
    if start_date:
        query = query.where(Trade.trading_date >= start_date)
    if end_date:
        query = query.where(Trade.trading_date <= end_date)
    total = _count(session, query)
    rows = session.scalars(query.order_by(Trade.trade_number).limit(limit).offset(offset))
    return TradePage(total=total, items=[TradeResponse.model_validate(r) for r in rows])


@router.get("/equity")
def equity(job_id: uuid.UUID, session: SessionDep) -> list[EquityPointResponse]:
    job = _completed(session, job_id)
    rows = session.scalars(
        select(EquityCurvePoint)
        .where(EquityCurvePoint.backtest_job_id == job.id)
        .order_by(EquityCurvePoint.ts)
    )
    return [EquityPointResponse.model_validate(r) for r in rows]


def _daily(session: Session, job: BacktestJob) -> list[DailyPerformance]:
    return list(
        session.scalars(
            select(DailyPerformance)
            .where(DailyPerformance.backtest_job_id == job.id)
            .order_by(DailyPerformance.trading_date)
        )
    )


@router.get("/daily")
def daily(job_id: uuid.UUID, session: SessionDep) -> list[DailyPerformanceResponse]:
    job = _completed(session, job_id)
    return [DailyPerformanceResponse.model_validate(r) for r in _daily(session, job)]


@router.get("/monthly")
def monthly(job_id: uuid.UUID, session: SessionDep) -> list[DailyPerformanceResponse]:
    job = _completed(session, job_id)
    rows = [
        PeriodPerformance(r.trading_date, r.trades, r.wins, r.losses, r.net_points)
        for r in _daily(session, job)
    ]
    return [
        DailyPerformanceResponse(
            trading_date=m.period, trades=m.trades, wins=m.wins, losses=m.losses,
            net_points=m.net_points,
        )
        for m in monthly_performance(rows)
    ]  # fmt: skip


@router.get("/decisions")
def decisions(
    job_id: uuid.UUID,
    session: SessionDep,
    action: Literal["BUY", "SELL", "HOLD"] | None = None,
    reason_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: Limit = 500,
    offset: Offset = 0,
) -> DecisionPage:
    job = _completed(session, job_id)
    query = (
        select(StrategyDecision, MarketContext)
        .join(MarketContext, MarketContext.decision_id == StrategyDecision.id)
        .where(StrategyDecision.backtest_job_id == job.id)
    )
    if action:
        query = query.where(StrategyDecision.action == action)
    if reason_code:
        query = query.where(StrategyDecision.reason_codes.contains([reason_code]))
    # Exchange-local dates become exact UTC bounds, independent of the database's timezone data.
    if start_date:
        query = query.where(StrategyDecision.candle_ts >= _exchange_midnight(start_date))
    if end_date:
        next_day = end_date + timedelta(days=1)
        query = query.where(StrategyDecision.candle_ts < _exchange_midnight(next_day))
    total = _count(session, query)
    rows = session.execute(query.order_by(StrategyDecision.candle_ts).limit(limit).offset(offset))
    return DecisionPage(
        total=total,
        items=[
            DecisionResponse.model_validate(
                {
                    **{c.key: getattr(decision, c.key) for c in StrategyDecision.__table__.columns},
                    "market_context": {
                        c.key: getattr(context, c.key)
                        for c in MarketContext.__table__.columns
                        if c.key != "decision_id"
                    },
                }
            )
            for decision, context in rows
        ],
    )
