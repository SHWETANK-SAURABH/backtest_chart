"""The fixed shape of an AI dataset record.

Features are known when the decision is made. Labels include the decision itself and outcomes that
are only known later. The validator rejects any feature not listed here, so a future outcome cannot
slip into the inputs unnoticed.
"""

MARKET_CONTEXT_FEATURES = (
    "close",
    "price_vs_ema20",
    "ema20_direction",
    "cpr_position",
    "distance_to_daily_tc_percent",
    "distance_to_daily_bc_percent",
    "distance_to_weekly_tc_percent",
    "distance_to_weekly_bc_percent",
    "cpr_width_percent",
    "cpr_histogram",
    "daily_cpr_relationship",
    "weekly_cpr_relationship",
    "daily_cpr_bias",
    "camarilla_relationship",
    "price_vs_cam_h3",
    "price_vs_cam_l3",
    "adr_points",
    "adr_usage_percent",
    "adr_remaining_points",
    "market_regime",
    "trend",
    "volatility",
    "gap",
    "session_part",
    "weekday",
    "minutes_since_open",
)

STRATEGY_STATE_FEATURES = (
    "long_permission",
    "short_permission",
    "market_state",
    "aggression",
    "table_tennis",
    "reversal_signals",
    "reversal_setup",
    "position_before",
)

DECISION_LABELS = ("action", "reason_codes")

OUTCOME_LABELS = (
    "trade_taken",
    "trade_net_points",
    "trade_result",
    "exit_reason",
    "holding_seconds",
    "setup_outcome",
)

ACTIONS = {"BUY", "SELL", "HOLD"}
TRADE_RESULTS = {"win", "loss", "breakeven", None}
SETUP_OUTCOMES = {"taken_win", "taken_loss", "taken_breakeven", "skipped", "no_setup"}
SPLITS = ("train", "validation", "test")


def forward_return_label(bars: int) -> str:
    return f"forward_return_points_{bars}_bars"
