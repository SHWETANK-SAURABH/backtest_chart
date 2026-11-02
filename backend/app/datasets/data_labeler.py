"""Labels: the strategy's decision, and outcomes known only after the decision.

Outcome labels never become features. Forward returns stay within one session, so a label never
reaches into the next session, which keeps whole-session splits free of overlap.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from app.data.calendar.nse import BAR_MINUTES
from app.datasets.schema import forward_return_label

BAR = timedelta(minutes=BAR_MINUTES)
SKIPPED_CODES = {"REVERSAL_NOT_AT_MTZ", "NO_TARGET_ZONE", "INVALID_STOP", "CONFLICTING_SIGNALS"}


def trades_by_signal_time(trades: Sequence[dict[str, Any]]) -> dict[datetime, dict[str, Any]]:
    """Both execution methods enter one candle after the signal candle opened, so the signal
    candle is the one that opened one bar before the entry time."""
    return {trade["entry_ts"] - BAR: trade for trade in trades}


def _result(net: float) -> str:
    return "win" if net > 0 else "loss" if net < 0 else "breakeven"


def decision_labels(decision: dict[str, Any]) -> dict[str, Any]:
    return {"action": decision["action"], "reason_codes": list(decision["reason_codes"])}


def outcome_labels(
    decision: dict[str, Any],
    trade: dict[str, Any] | None,
    session_closes: Sequence[float],
    index_in_session: int,
    horizons: Sequence[int],
) -> dict[str, Any]:
    codes = set(decision["reason_codes"])
    if trade is not None:
        setup_outcome = f"taken_{_result(trade['net_points'])}"
    elif decision["action"] in ("BUY", "SELL") or codes & SKIPPED_CODES:
        # A setup the strategy saw but did not trade: away from an MTZ, no target, or ignored
        # by execution (open position, risk limit, session closing, gap past a level).
        setup_outcome = "skipped"
    else:
        setup_outcome = "no_setup"

    labels: dict[str, Any] = {
        "trade_taken": trade is not None,
        "trade_net_points": trade["net_points"] if trade else None,
        "trade_result": _result(trade["net_points"]) if trade else None,
        "exit_reason": trade["exit_reason"] if trade else None,
        "holding_seconds": trade["holding_seconds"] if trade else None,
        "setup_outcome": setup_outcome,
    }
    close = session_closes[index_in_session]
    for bars in horizons:
        later = index_in_session + bars
        labels[forward_return_label(bars)] = (
            session_closes[later] - close if later < len(session_closes) else None
        )
    return labels
