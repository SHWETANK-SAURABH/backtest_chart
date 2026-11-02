"""Decision-time features, built only from one stored decision and the candle before it."""

from typing import Any

from app.domain.candle import EXCHANGE_TZ


def _relative(price: float, level: float | None) -> str | None:
    if level is None:
        return None
    return "above" if price > level else "below" if price < level else "at"


def _distance_percent(price: float, level: float | None) -> float | None:
    if level is None or level == 0:
        return None
    return (price - level) / level * 100


def build_features(
    decision: dict[str, Any], context: dict[str, Any], position_before: str
) -> dict[str, dict[str, Any]]:
    """`position_before` is the position after the previous candle in the same session."""
    close = decision["close"]
    daily = (context.get("cpr") or {}).get("daily") or {}
    weekly = (context.get("cpr") or {}).get("weekly") or {}
    camarilla = context.get("camarilla") or {}
    adr = context.get("adr") or {}
    labels = context.get("condition_labels") or {}
    direction = (decision.get("trade_engine_state") or {}).get("trade_direction") or {}
    signals = (decision.get("reversal_state") or {}).get("signals") or []

    tc, bc = daily.get("tc"), daily.get("bc")
    cpr_position = None
    if tc is not None and bc is not None:
        cpr_position = "above_tc" if close > tc else "below_bc" if close < bc else "inside_cpr"

    local = decision["candle_ts"].astimezone(EXCHANGE_TZ)
    minutes_since_open = (local.hour * 60 + local.minute) - (9 * 60 + 15)

    market_context = {
        "close": close,
        "price_vs_ema20": _relative(close, context.get("ema20")),
        "ema20_direction": context.get("ema_direction"),
        "cpr_position": cpr_position,
        "distance_to_daily_tc_percent": _distance_percent(close, tc),
        "distance_to_daily_bc_percent": _distance_percent(close, bc),
        "distance_to_weekly_tc_percent": _distance_percent(close, weekly.get("tc")),
        "distance_to_weekly_bc_percent": _distance_percent(close, weekly.get("bc")),
        "cpr_width_percent": daily.get("width_percent"),
        "cpr_histogram": daily.get("histogram") if tc is not None else None,
        "daily_cpr_relationship": daily.get("relationship") if tc is not None else None,
        "weekly_cpr_relationship": weekly.get("relationship") if weekly.get("tc") else None,
        "daily_cpr_bias": daily.get("bias") if tc is not None else None,
        "camarilla_relationship": camarilla.get("relationship") if camarilla.get("h3") else None,
        "price_vs_cam_h3": _relative(close, camarilla.get("h3")),
        "price_vs_cam_l3": _relative(close, camarilla.get("l3")),
        "adr_points": adr.get("value"),
        "adr_usage_percent": adr.get("usage_percent"),
        "adr_remaining_points": adr.get("remaining"),
        "market_regime": context.get("market_regime"),
        "trend": labels.get("trend"),
        "volatility": labels.get("volatility"),
        "gap": labels.get("gap"),
        "session_part": labels.get("session_part"),
        "weekday": labels.get("weekday"),
        "minutes_since_open": minutes_since_open,
    }
    strategy_state = {
        "long_permission": decision.get("long_permission"),
        "short_permission": decision.get("short_permission"),
        "market_state": direction.get("market_state"),
        "aggression": direction.get("aggression"),
        "table_tennis": direction.get("table_tennis"),
        "reversal_signals": sorted(f"{s['code']}_{s['side']}" for s in signals),
        "reversal_setup": bool(signals),
        "position_before": position_before,
    }
    return {"market_context": market_context, "strategy_state": strategy_state}
