"""Chronological, event-driven execution of strategy decisions.

For each confirmed candle, in order:
1. Fill an entry pending from the previous candle (next-open execution).
2. Check the open position's stop and target against this candle.
3. Act on this candle's decision, known only at its close.
4. Square off at the session's final candle.

Assumptions, recorded with every trade:
- Signal-close entries fill at the signal candle's close. That price is only known as the candle
  closes, so this is idealised; next-open entries are the realistic comparison.
- A stop or target touched inside a candle fills at that level. It is timestamped at the candle's
  close, the earliest moment it is certain to have happened.
- If one candle touches both, the stop is assumed to have come first.
- A candle opening beyond the stop exits at the open; one opening beyond the target fills there too.
- There is one position at a time. Signals while a position is open, or in the opposite direction,
  are ignored.
- No position is held overnight.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from app.backtesting.settings import ExecutionSettings, RiskSettings
from app.costs.models import CostModel, SpotIndexNoCosts
from app.data.calendar.nse import BAR_MINUTES
from app.domain.enums import DecisionAction, ExecutionMethod, Side
from app.portfolio.position import ClosedTrade, DailyRiskTracker, Position
from app.strategy.engine import Decision

BAR = timedelta(minutes=BAR_MINUTES)


class Evaluation(Protocol):
    @property
    def decision(self) -> Decision: ...

    @property
    def final_bar_of_session(self) -> bool: ...


@dataclass
class BarRecord:
    """A decision together with what execution did on that candle."""

    decision: Decision
    trade_opened: bool = False
    position_closed: bool = False
    position_state: str = "flat"
    execution_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PendingEntry:
    side: Side
    trading_date: date
    stop_loss: float
    target: float
    reasons: list[str]
    context: dict[str, Any]


@dataclass
class BacktestResult:
    records: list[BarRecord]
    trades: list[ClosedTrade]
    equity: list[tuple[datetime, float]]
    assumptions: dict[str, Any]

    def result_hash(self) -> str:
        """Identifies the outcome, so a rerun can be checked for identical results."""
        payload = {
            "trades": [
                [t.number, t.side, t.entry_time.isoformat(), t.exit_time.isoformat(),
                 repr(t.entry_price), repr(t.exit_price), t.exit_reason, repr(t.net_points)]
                for t in self.trades
            ],
            "decisions": [
                [r.decision.timestamp.isoformat(), r.decision.action, r.decision.reason_codes,
                 r.trade_opened, r.position_closed, r.position_state, r.execution_notes]
                for r in self.records
            ],
        }  # fmt: skip
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class BacktestEngine:
    def __init__(
        self,
        execution: ExecutionSettings | None = None,
        risk: RiskSettings | None = None,
        cost_model: CostModel | None = None,
    ) -> None:
        self.execution = execution or ExecutionSettings()
        self.risk = risk or RiskSettings()
        self.cost_model = cost_model or SpotIndexNoCosts()

    def assumptions(self) -> dict[str, Any]:
        return {
            "execution_method": self.execution.method.value,
            "signal_close_is_idealised": self.execution.method == ExecutionMethod.SIGNAL_CLOSE,
            "slippage_points": self.execution.slippage_points,
            "same_candle_policy": self.execution.same_candle_policy.value,
            "intrabar_exit_time": "close of the candle that touched the level",
            "positions": "one at a time, intraday only",
            "cost_model": self.cost_model.code,
            "units": "theoretical NIFTY 50 index points, not rupees",
        }

    def run(
        self, evaluations: Iterable[Evaluation], trade_from: date | None = None
    ) -> BacktestResult:
        """Simulate in order. Candles before `trade_from` only warm up the strategy."""
        run = _Run(self, trade_from)
        for evaluation in evaluations:
            run.step(evaluation.decision, evaluation.final_bar_of_session)
        run.finish()
        return BacktestResult(run.records, run.trades, run.equity, self.assumptions())


class _Run:
    def __init__(self, engine: BacktestEngine, trade_from: date | None) -> None:
        self.settings = engine.execution
        self.cost_model = engine.cost_model
        self.risk = DailyRiskTracker(
            engine.risk.max_trades_per_day, engine.risk.max_daily_loss_points
        )
        self.trade_from = trade_from
        self.position: Position | None = None
        self.pending: PendingEntry | None = None
        self.records: list[BarRecord] = []
        self.trades: list[ClosedTrade] = []
        self.equity: list[tuple[datetime, float]] = []
        self.cumulative = 0.0
        self.previous: BarRecord | None = None

    @property
    def slippage(self) -> float:
        return self.settings.slippage_points

    def step(self, decision: Decision, final_bar: bool) -> None:
        if self.trade_from is not None and decision.trading_date < self.trade_from:
            return
        record = BarRecord(decision)

        # Data ended a session without its final candle: square off at the last known close.
        if self.position is not None and decision.trading_date != self.position.trading_date:
            assert self.previous is not None
            self._close(
                self.previous, self.previous.decision.close, "SESSION_END_MISSING_DATA", market=True
            )
            self.previous.position_state = "flat"
        if self.pending is not None and decision.trading_date != self.pending.trading_date:
            record.execution_notes.append("PENDING_ENTRY_CANCELLED_NEW_SESSION")
            self.pending = None

        if self.pending is not None:
            self._fill_pending(record)
        # Positions from earlier candles, or filled at this candle's open, can exit within it.
        if self.position is not None:
            self._check_exits(record)
        self._act_on_decision(record, final_bar)
        if final_bar and self.position is not None:
            self._close(record, decision.close, "EOD_SQUARE_OFF", market=True)

        record.position_state = self.position.side.value if self.position else "flat"
        self.records.append(record)
        self.previous = record

    def finish(self) -> None:
        if self.position is not None and self.previous is not None:
            self._close(self.previous, self.previous.decision.close, "END_OF_DATA", market=True)
            self.previous.position_state = "flat"

    def _fill_pending(self, record: BarRecord) -> None:
        pending, bar = self.pending, record.decision
        assert pending is not None
        self.pending = None
        long = pending.side == Side.LONG
        if (long and bar.open <= pending.stop_loss) or (not long and bar.open >= pending.stop_loss):
            record.execution_notes.append("ENTRY_SKIPPED_OPEN_BEYOND_STOP")
            return
        if (long and bar.open >= pending.target) or (not long and bar.open <= pending.target):
            record.execution_notes.append("ENTRY_SKIPPED_OPEN_BEYOND_TARGET")
            return
        price = bar.open + self.slippage if long else bar.open - self.slippage
        self._open(record, pending.side, bar.timestamp, price, pending)

    def _open(
        self, record: BarRecord, side: Side, time: datetime, price: float, signal: PendingEntry
    ) -> None:
        self.position = Position(
            side=side,
            trading_date=record.decision.trading_date,
            entry_time=time,
            entry_price=price,
            stop_loss=signal.stop_loss,
            target=signal.target,
            entry_reasons=signal.reasons,
            entry_context=signal.context,
        )
        self.risk.record_entry(record.decision.trading_date)
        record.trade_opened = True

    def _check_exits(self, record: BarRecord) -> None:
        position, bar = self.position, record.decision
        assert position is not None
        long = position.side == Side.LONG
        stop, target = position.stop_loss, position.target

        if (long and bar.open <= stop) or (not long and bar.open >= stop):
            self._close(record, bar.open, "STOP_LOSS_GAP", market=True, time=bar.timestamp)
            return
        if (long and bar.open >= target) or (not long and bar.open <= target):
            self._close(record, bar.open, "TARGET_GAP", market=False, time=bar.timestamp)
            return

        stop_hit = bar.low <= stop if long else bar.high >= stop
        target_hit = bar.high >= target if long else bar.low <= target
        if stop_hit and target_hit:
            record.execution_notes.append("STOP_AND_TARGET_SAME_CANDLE_STOP_ASSUMED")
            self._close(record, stop, "STOP_LOSS", market=True, ambiguous=True)
        elif stop_hit:
            self._close(record, stop, "STOP_LOSS", market=True)
        elif target_hit:
            self._close(record, target, "TARGET", market=False)

    def _act_on_decision(self, record: BarRecord, final_bar: bool) -> None:
        decision = record.decision
        if decision.action == DecisionAction.HOLD or decision.signal is None:
            return
        side = Side.LONG if decision.action == DecisionAction.BUY else Side.SHORT
        if self.position is not None:
            record.execution_notes.append("SIGNAL_IGNORED_POSITION_OPEN")
            return
        if final_bar:
            record.execution_notes.append("SIGNAL_IGNORED_SESSION_CLOSING")
            return
        blocked = self.risk.entry_block_reason(decision.trading_date)
        if blocked:
            record.execution_notes.append(f"SIGNAL_IGNORED_{blocked}")
            return

        entry = PendingEntry(
            side,
            decision.trading_date,
            decision.signal.stop_loss,
            decision.signal.target,
            decision.reason_codes,
            decision.context,
        )
        if self.settings.method == ExecutionMethod.NEXT_OPEN:
            self.pending = entry
            record.execution_notes.append("ENTRY_PENDING_NEXT_OPEN")
            return
        price = (
            decision.close + self.slippage if side == Side.LONG else decision.close - self.slippage
        )
        self._open(record, side, decision.timestamp + BAR, price, entry)

    def _close(
        self,
        record: BarRecord,
        level: float,
        reason: str,
        market: bool,
        time: datetime | None = None,
        ambiguous: bool = False,
    ) -> None:
        position = self.position
        assert position is not None
        long = position.side == Side.LONG
        price = level
        if market:
            price = level - self.slippage if long else level + self.slippage
        gross = position.points(price)
        cost = self.cost_model.round_trip_cost_points(position.entry_price, price)
        exit_time = time or record.decision.timestamp + BAR
        notes = ["SAME_CANDLE_AMBIGUITY"] if ambiguous else []
        trade = ClosedTrade(
            number=len(self.trades) + 1,
            trading_date=position.trading_date,
            side=position.side,
            entry_time=position.entry_time,
            exit_time=exit_time,
            entry_price=position.entry_price,
            exit_price=price,
            stop_loss=position.stop_loss,
            target=position.target,
            exit_reason=reason,
            gross_points=gross,
            cost_points=cost,
            net_points=gross - cost,
            entry_reasons=position.entry_reasons,
            entry_context=position.entry_context,
            exit_context=record.decision.context,
            notes=notes,
        )
        self.trades.append(trade)
        self.risk.record_exit(position.trading_date, trade.net_points)
        self.cumulative += trade.net_points
        self.equity.append((exit_time, self.cumulative))
        self.position = None
        record.position_closed = True
