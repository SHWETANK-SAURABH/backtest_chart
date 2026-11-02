"""Market condition labels, built only from information known at decision time.

Every label comes from a stored decision's context. Thresholds that are not in the Pine script are
choices documented in docs/analytics.md.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, time
from typing import Any

from app.domain.candle import EXCHANGE_TZ

GAP_THRESHOLD_PERCENT = 0.25
OPENING_HOUR_END = time(10, 15)
AFTERNOON_START = time(13, 30)
# The script's ADR contraction and expansion ratios, applied to the previous session's range.
LOW_VOLATILITY_RATIO = 0.65
HIGH_VOLATILITY_RATIO = 1.25
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _trend(context: dict[str, Any]) -> str | None:
    histogram = (context.get("cpr_daily") or {}).get("histogram")
    if histogram is None or (context.get("cpr_daily") or {}).get("tc") is None:
        return None
    return "trending" if histogram in ("Trending", "Possible Trending") else "sideways"


def _volatility(context: dict[str, Any]) -> str | None:
    cpr = context.get("cpr_daily") or {}
    adr = (context.get("adr") or {}).get("value")
    if cpr.get("ph") is None or cpr.get("pl") is None or not adr:
        return None
    ratio = (cpr["ph"] - cpr["pl"]) / adr
    if ratio > HIGH_VOLATILITY_RATIO:
        return "high_volatility"
    if ratio < LOW_VOLATILITY_RATIO:
        return "low_volatility"
    return "normal_volatility"


def _gap(context: dict[str, Any]) -> str | None:
    session_open = context.get("session_open")
    previous_close = (context.get("camarilla_daily") or {}).get("center")
    if session_open is None or not previous_close:
        return None
    change = (session_open - previous_close) / previous_close * 100
    if change >= GAP_THRESHOLD_PERCENT:
        return "gap_up"
    if change <= -GAP_THRESHOLD_PERCENT:
        return "gap_down"
    return "no_gap"


def _session_part(moment: datetime) -> str:
    local = moment.astimezone(EXCHANGE_TZ).time()
    if local < OPENING_HOUR_END:
        return "opening_hour"
    if local < AFTERNOON_START:
        return "midday"
    return "afternoon"


def _adr_usage(context: dict[str, Any]) -> str | None:
    usage = (context.get("adr") or {}).get("usage_percent")
    if usage is None:
        return None
    if usage < 50:
        return "below_50"
    if usage <= 100:
        return "50_to_100"
    return "above_100"


def labels(context: dict[str, Any], moment: datetime) -> dict[str, str | None]:
    """Condition labels for a decision taken at `moment` (the candle's open time)."""
    local = moment.astimezone(EXCHANGE_TZ)
    return {
        "trend": _trend(context),
        "volatility": _volatility(context),
        "gap": _gap(context),
        "session_part": _session_part(moment),
        "hour": f"{local.hour:02d}:00",
        "weekday": WEEKDAYS[local.weekday()],
        "adr_usage": _adr_usage(context),
        "cpr_width": (context.get("cpr_daily") or {}).get("histogram")
        if (context.get("cpr_daily") or {}).get("tc") is not None
        else None,
    }


def regime(context: dict[str, Any], moment: datetime) -> str | None:
    """A single label for storage: trend and volatility, such as 'trending_low_volatility'."""
    result = labels(context, moment)
    if result["trend"] is None or result["volatility"] is None:
        return None
    return f"{result['trend']}_{result['volatility']}"


def performance_by_condition(
    trades: Iterable[tuple[dict[str, str | None], float]],
    setups: Iterable[tuple[list[str], float]] = (),
) -> dict[str, dict[str, dict[str, Any]]]:
    """Group (labels, net points) pairs into per-category, per-label statistics."""
    groups: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for trade_labels, net in trades:
        for category, label in trade_labels.items():
            groups[category][label or "unknown"].append(net)
    for patterns, net in setups:
        for pattern in patterns:
            groups["setup"][pattern].append(net)
    return {
        category: {
            label: {
                "trades": len(results),
                "wins": sum(1 for r in results if r > 0),
                "losses": sum(1 for r in results if r < 0),
                "net_points": sum(results),
                "win_rate": sum(1 for r in results if r > 0) / len(results),
                "average_points": sum(results) / len(results),
            }
            for label, results in sorted(by_label.items())
        }
        for category, by_label in sorted(groups.items())
    }
