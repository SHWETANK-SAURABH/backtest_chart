# Analytics

Code: `backend/app/analytics`. Calculated when a backtest completes, and saved in
`backtest_metrics`, `equity_curve` and `daily_performance`.

## Units

| Unit | Available | Notes |
| --- | --- | --- |
| Index points | Yes | Every metric below |
| Percent of index | Yes | Each trade's net points as a percent of its entry level, uncompounded |
| Hypothetical money | No | Spot has no contract multiplier; needs a futures or options model |
| Actual money | No | Spot results are theoretical |

`unit_summary` in the metrics records all four, with the reason where one is unavailable.

## Trade statistics

A win is a trade with net points above zero, a loss below zero, and breakeven exactly zero.

| Metric | Definition | When undefined (None) |
| --- | --- | --- |
| Win rate | wins / total trades | No trades |
| Gross profit | Sum of winning trades | |
| Gross loss | Sum of losing trades, as a positive number | |
| Profit factor | gross profit / gross loss | No losing trades |
| Average win, average loss | Mean of wins; mean of losses (negative) | No wins; no losses |
| Expectancy | win rate x average win + loss rate x average loss | No trades |
| Average trade | net points / total trades (equals expectancy) | No trades |
| Consecutive wins and losses | Longest run; a breakeven trade ends a run | |
| Average holding time | Mean of exit time minus entry time | No trades |

Breakeven trades are total minus winning minus losing.

## Equity curve and drawdown

The curve is cumulative net points after each exit, starting from 0. Drawdown at each point is the
running peak minus the current value, where the peak starts at 0. A first trade that loses therefore
counts as a drawdown. Maximum drawdown is the largest such value.

## Daily and monthly performance

Daily rows cover every tested session, including sessions without trades, so averages are not
inflated. Monthly rows sum daily rows and are labelled by the first day of the month.

## Sharpe ratio

| Assumption | Value |
| --- | --- |
| Series | Net points per tested session, including sessions without trades |
| Frequency | Daily |
| Annualisation | mean / sample standard deviation x sqrt(252) |
| Risk-free rate | 0 |

It is computed on points, not percentage returns, so it is comparable between versions of this
strategy on NIFTY 50 but not with Sharpe ratios of other assets. It is undefined with fewer than two
sessions, or when every session has the same result.

## Market condition labels

Labels use only the decision's stored context, so nothing from later in the session is used. Trades
are labelled from their entry decision.

| Category | Labels | Definition | Source |
| --- | --- | --- | --- |
| `trend` | trending, sideways | Daily CPR width "Trending" or "Possible Trending" is trending; wider is sideways | Script's histogram |
| `volatility` | low, normal, high | Previous session's range / ADR: below 0.65 low, above 1.25 high | Script's ADR contraction and expansion ratios |
| `gap` | gap_up, gap_down, no_gap | Session open against previous close, threshold 0.25% | **Choice** |
| `session_part` | opening_hour, midday, afternoon | Before 10:15, before 13:30, after | **Choice** |
| `hour` | 09:00 ... 15:00 | Hour of the decision candle | |
| `weekday` | monday ... friday | | |
| `adr_usage` | below_50, 50_to_100, above_100 | Session range so far as % of ADR | **Choice** of bands |
| `cpr_width` | Script's four histogram states | Daily CPR width | Script |
| `setup` | OR, DR, ER, WR | The reversal patterns behind the entry | Script |

The stored `market_regime` combines trend and volatility, such as `trending_low_volatility`. It is
empty when either is unknown, for example before 10 sessions of ADR history exist.

Thresholds marked **Choice** are not in the script. They live in `analytics/regimes.py` and can be
changed.

`by_market_condition` in the metrics gives, for each category and label: trades, wins, losses, net
points, win rate and average points.

## Endpoints

| Endpoint | Returns |
| --- | --- |
| `GET /backtests/{id}/metrics` | Everything above |
| `GET /backtests/{id}/trades` | Trades; filters `side`, `outcome`, `exit_reason`, `start_date`, `end_date`; `limit`, `offset` |
| `GET /backtests/{id}/equity` | Equity curve with drawdown |
| `GET /backtests/{id}/daily` | Daily performance |
| `GET /backtests/{id}/monthly` | Monthly performance |
| `GET /backtests/{id}/decisions` | Every candle's decision and market context; filters `action`, `reason_code`, `start_date`, `end_date`; `limit`, `offset` |

All return 409 until the backtest has completed.
