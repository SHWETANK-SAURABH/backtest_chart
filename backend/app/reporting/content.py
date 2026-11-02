"""Report content, independent of the output format."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.metrics import PeriodPerformance, monthly_performance
from app.analytics.regimes import (
    AFTERNOON_START,
    GAP_THRESHOLD_PERCENT,
    HIGH_VOLATILITY_RATIO,
    LOW_VOLATILITY_RATIO,
    OPENING_HOUR_END,
)
from app.database.models import (
    BacktestJob,
    BacktestMetrics,
    DailyPerformance,
    Dataset,
    Instrument,
    MarketContext,
    Strategy,
    StrategyDecision,
    StrategyVersion,
    Trade,
)
from app.domain.candle import EXCHANGE_TZ
from app.domain.enums import ReportCategory

POINTS_NOTICE = (
    "All results are theoretical NIFTY 50 spot index points. The spot index cannot be traded, so "
    "these figures are not rupee profits or losses."
)


@dataclass
class Section:
    title: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    text: str | None = None


@dataclass
class ReportContent:
    category: ReportCategory
    title: str
    metadata: dict[str, Any]
    # The flat table exported to CSV and Parquet.
    main_table: Section
    sections: list[Section]


def _local(moment: datetime | None) -> str | None:
    return moment.astimezone(EXCHANGE_TZ).isoformat() if moment else None


def _dataset_label(dataset: Dataset) -> str:
    return f"{dataset.timeframe} v{dataset.version} ({dataset.content_hash[:12]})"


def build_metadata(session: Session, job: BacktestJob, generated_at: datetime) -> dict[str, Any]:
    version = session.get_one(StrategyVersion, job.strategy_version_id)
    strategy = session.get_one(Strategy, version.strategy_id)
    intraday = session.get_one(Dataset, job.intraday_dataset_id)
    daily = session.get_one(Dataset, job.daily_dataset_id)
    instrument = session.get_one(Instrument, job.instrument_id)
    return {
        "backtest_id": str(job.id),
        "strategy": strategy.name,
        "strategy_version": version.version,
        "strategy_code_hash": version.code_hash,
        "intraday_dataset": _dataset_label(intraday),
        "daily_dataset": _dataset_label(daily),
        "generated_at": generated_at.isoformat(),
        "instrument": instrument.symbol,
        "exchange": instrument.exchange,
        "timeframe": job.timeframe,
        "date_range": f"{job.start_date.isoformat()} to {job.end_date.isoformat()}",
        "execution_method": job.execution_method,
        "execution_settings": job.execution_settings,
        "risk_settings": job.risk_settings,
        "capital_assumptions": job.capital_assumptions,
        "input_hash": job.input_hash,
        "result_hash": job.result_hash,
        "units": "theoretical index points",
        "notice": POINTS_NOTICE,
    }


def _metrics_rows(metrics: BacktestMetrics) -> list[dict[str, Any]]:
    names = [
        "total_trades", "winning_trades", "losing_trades", "win_rate", "gross_profit_points",
        "gross_loss_points", "net_points", "profit_factor", "max_drawdown_points",
        "average_trade_points", "average_win_points", "average_loss_points", "expectancy_points",
        "average_holding_seconds", "max_consecutive_wins", "max_consecutive_losses", "sharpe_ratio",
    ]  # fmt: skip
    rows = [{"metric": name, "value": getattr(metrics, name)} for name in names]
    breakeven = metrics.total_trades - metrics.winning_trades - metrics.losing_trades
    rows.insert(3, {"metric": "breakeven_trades", "value": breakeven})
    return rows


def _period_rows(rows: list[PeriodPerformance], label: str) -> list[dict[str, Any]]:
    return [
        {label: r.period.isoformat(), "trades": r.trades, "wins": r.wins, "losses": r.losses,
         "net_points": r.net_points}
        for r in rows
    ]  # fmt: skip


CONDITION_ORDER = [
    "trend", "volatility", "gap", "session_part", "hour", "weekday", "adr_usage", "cpr_width",
    "setup",
]  # fmt: skip
CONDITION_COLUMNS = ["trades", "wins", "losses", "win_rate", "net_points", "average_points"]


def _condition_rows(by_condition: dict[str, Any]) -> list[dict[str, Any]]:
    """Fixed category and column order; stored JSON does not preserve key order."""
    categories = sorted(
        by_condition,
        key=lambda c: (
            CONDITION_ORDER.index(c) if c in CONDITION_ORDER else len(CONDITION_ORDER),
            c,
        ),
    )
    return [
        {"category": category, "label": label, **{k: stats.get(k) for k in CONDITION_COLUMNS}}
        for category in categories
        for label, stats in sorted(by_condition[category].items())
    ]


def _unit_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per unit, in the same three columns, so every unit is shown."""
    points = summary.get("points", {})
    percent = summary.get("percent_of_index", {})
    average = percent.get("average_trade_return")
    average_text = "n/a" if average is None else f"{average:.4f}%"
    rows = [
        {"unit": "points", "value": points.get("net"), "note": "Net theoretical index points"},
        {
            "unit": "percent_of_index",
            "value": percent.get("sum_of_trade_returns"),
            "note": f"Sum of trade returns, in percent; average per trade {average_text}. "
            f"{percent.get('note', '')}",
        },
    ]
    for unit in ("hypothetical_monetary", "actual_monetary"):
        values = summary.get(unit, {})
        rows.append({"unit": unit, "value": values.get("value"), "note": values.get("reason")})
    return rows


def performance(session: Session, job: BacktestJob, metadata: dict[str, Any]) -> ReportContent:
    metrics = session.get_one(BacktestMetrics, job.id)
    daily = [
        PeriodPerformance(r.trading_date, r.trades, r.wins, r.losses, r.net_points)
        for r in session.scalars(
            select(DailyPerformance)
            .where(DailyPerformance.backtest_job_id == job.id)
            .order_by(DailyPerformance.trading_date)
        )
    ]
    main = Section("Performance metrics", _metrics_rows(metrics))
    return ReportContent(
        ReportCategory.PERFORMANCE,
        "Backtest performance report",
        metadata,
        main,
        [
            main,
            Section("Units", _unit_rows(metrics.unit_summary)),
            Section(
                "Sharpe ratio assumptions",
                [{"assumption": k, "value": v} for k, v in metrics.sharpe_assumptions.items()],
            ),
            Section("Monthly performance", _period_rows(monthly_performance(daily), "month")),
            Section("Daily performance", _period_rows(daily, "date")),
            Section(
                "Performance by market condition", _condition_rows(metrics.by_market_condition)
            ),
        ],
    )


def _trade_rows(trades: list[Trade]) -> list[dict[str, Any]]:
    rows = []
    for t in trades:
        entry = t.indicators_at_entry
        rows.append(
            {
                "trade_number": t.trade_number,
                "date": t.trading_date.isoformat(),
                "side": t.side,
                "entry_time": _local(t.entry_ts),
                "exit_time": _local(t.exit_ts),
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "stop_loss": t.stop_loss,
                "target": t.target,
                "exit_reason": t.exit_reason,
                "holding_seconds": t.holding_seconds,
                "gross_points": t.gross_points,
                "cost_points": t.cost_points,
                "net_points": t.net_points,
                "market_regime": t.market_regime,
                "entry_reasons": " ".join(t.decision_reason),
                "entry_cpr_tc": (entry.get("cpr_daily") or {}).get("tc"),
                "entry_cpr_bc": (entry.get("cpr_daily") or {}).get("bc"),
                "entry_weekly_tc": (entry.get("cpr_weekly") or {}).get("tc"),
                "entry_weekly_bc": (entry.get("cpr_weekly") or {}).get("bc"),
                "entry_adr_usage_percent": (entry.get("adr") or {}).get("usage_percent"),
                "entry_ema20": entry.get("ema_slow"),
                "exit_ema20": t.indicators_at_exit.get("ema_slow"),
                "execution_method": t.execution_assumptions.get("execution_method"),
                "slippage_points": t.execution_assumptions.get("slippage_points"),
                "notes": " ".join(t.execution_assumptions.get("notes", [])),
            }
        )
    return rows


def trades(session: Session, job: BacktestJob, metadata: dict[str, Any]) -> ReportContent:
    rows = _trade_rows(
        list(
            session.scalars(
                select(Trade).where(Trade.backtest_job_id == job.id).order_by(Trade.trade_number)
            )
        )
    )
    main = Section("Trades", rows)
    return ReportContent(ReportCategory.TRADES, "Individual trade report", metadata, main, [main])


def _decision_row(decision: StrategyDecision, context: MarketContext) -> dict[str, Any]:
    daily_cpr = (context.cpr or {}).get("daily") or {}
    weekly_cpr = (context.cpr or {}).get("weekly") or {}
    cam = context.camarilla or {}
    entry = decision.reversal_state.get("entry_signal") or {}
    return {
        "time": _local(decision.candle_ts),
        "open": decision.open,
        "high": decision.high,
        "low": decision.low,
        "close": decision.close,
        "cpr_pp": daily_cpr.get("pp"),
        "cpr_tc": daily_cpr.get("tc"),
        "cpr_bc": daily_cpr.get("bc"),
        "cpr_width_percent": daily_cpr.get("width_percent"),
        "weekly_tc": weekly_cpr.get("tc"),
        "weekly_bc": weekly_cpr.get("bc"),
        "cam_h3": cam.get("h3"),
        "cam_l3": cam.get("l3"),
        "cam_h4": cam.get("h4"),
        "cam_l4": cam.get("l4"),
        "adr": (context.adr or {}).get("value"),
        "adr_usage_percent": context.adr_usage_percent,
        "ema20": context.ema20,
        "ema20_direction": context.ema_direction,
        "market_structure": "not defined in the Pine script",
        "market_regime": context.market_regime,
        "long_permission": decision.long_permission,
        "short_permission": decision.short_permission,
        "reversal_signals": " ".join(
            f"{s['code']}_{s['side']}" for s in decision.reversal_state.get("signals", [])
        ),
        "market_state": (decision.trade_engine_state.get("trade_direction") or {}).get(
            "market_state"
        ),
        "action": decision.action,
        "reason_codes": " ".join(decision.reason_codes),
        "explanation": decision.explanation,
        "stop_loss": entry.get("stop_loss"),
        "target": entry.get("target"),
        "execution_notes": " ".join(decision.trade_engine_state.get("execution_notes", [])),
        "trade_opened": decision.trade_opened,
        "position_closed": decision.position_closed,
        "position_after": decision.position_state,
    }


def decisions(session: Session, job: BacktestJob, metadata: dict[str, Any]) -> ReportContent:
    rows = [
        _decision_row(decision, context)
        for decision, context in session.execute(
            select(StrategyDecision, MarketContext)
            .join(MarketContext, MarketContext.decision_id == StrategyDecision.id)
            .where(StrategyDecision.backtest_job_id == job.id)
            .order_by(StrategyDecision.candle_ts)
        )
    ]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["action"]] = counts.get(row["action"], 0) + 1
    main = Section("Strategy decisions, every candle", rows)
    return ReportContent(
        ReportCategory.DECISIONS,
        "Strategy decision report",
        metadata,
        main,
        [
            Section(
                "Decision counts", [{"action": k, "candles": v} for k, v in sorted(counts.items())]
            ),
            main,
        ],
    )


REGIME_DEFINITIONS = [
    {"category": "trend", "definition": "Daily CPR width Trending or Possible Trending is "
     "trending; wider is sideways (the script's histogram)"},
    {"category": "volatility", "definition": f"Previous session range / ADR: below "
     f"{LOW_VOLATILITY_RATIO} low, above {HIGH_VOLATILITY_RATIO} high (the script's ratios)"},
    {"category": "gap", "definition": f"Session open against previous close, at least "
     f"{GAP_THRESHOLD_PERCENT}% (an implementation choice)"},
    {"category": "session_part", "definition": f"Opening hour before "
     f"{OPENING_HOUR_END:%H:%M}, afternoon from {AFTERNOON_START:%H:%M} "
     "(an implementation choice)"},
    {"category": "adr_usage", "definition": "Session range so far as a percent of ADR: below 50, "
     "50 to 100, above 100 (an implementation choice)"},
    {"category": "cpr_width", "definition": "The script's four CPR width histogram states"},
    {"category": "setup", "definition": "Reversal pattern behind the entry: OR, DR, ER, WR. "
     "Breakout setups are not traded by this strategy"},
    {"category": "hour, weekday", "definition": "Time of the entry decision, exchange time"},
]  # fmt: skip


def market_behaviour(session: Session, job: BacktestJob, metadata: dict[str, Any]) -> ReportContent:
    metrics = session.get_one(BacktestMetrics, job.id)
    main = Section("Performance by market condition", _condition_rows(metrics.by_market_condition))
    return ReportContent(
        ReportCategory.MARKET_BEHAVIOUR,
        "Market behaviour report",
        metadata,
        main,
        [
            main,
            Section(
                "How labels are calculated",
                REGIME_DEFINITIONS,
                text="Labels use only information known when each entry decision was made.",
            ),
        ],
    )


BUILDERS = {
    ReportCategory.PERFORMANCE: performance,
    ReportCategory.TRADES: trades,
    ReportCategory.DECISIONS: decisions,
    ReportCategory.MARKET_BEHAVIOUR: market_behaviour,
}


def build(
    session: Session, job: BacktestJob, category: ReportCategory, generated_at: datetime
) -> ReportContent:
    return BUILDERS[category](session, job, build_metadata(session, job, generated_at))
