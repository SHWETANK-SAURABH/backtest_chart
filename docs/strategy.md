# MTZ Reversal strategy

The port of the owner's Pine Script indicator, plus the entry rules the owner supplied. The script
itself is kept out of version control. Line numbers below refer to it.

## Source of each rule

The script is an `indicator()`, not a `strategy()`. It calculates levels and draws signals, but
places no trades. The trading rules come from the owner, confirmed on 2026-11-02 and extended twice
on 2026-11-03 (implementations 2.0.0 and 3.0.0).

| Rule | Source |
| --- | --- |
| CPR, Camarilla, ADR, EMA, hot zones, trade direction panel | Script, ported exactly |
| Reversal candles OR, DR, ER, WR | Script, lines 1394-1504 |
| Zones are the daily and weekly MTZ (BC to TC) | Owner |
| Enter on a reversal candle at an MTZ | Owner |
| Target the next MTZ in the trade direction | Owner |
| Stop at the signal candle's low (long) or high (short) | Owner |
| Trade direction panel does not gate entries | Owner |
| Each backtest chooses the entry patterns and the entry MTZ (daily, weekly or both) | Owner, 2026-11-03 |
| Targets can be any other MTZ, daily or weekly (daily-only entries target the weekly MTZ) | Owner, 2026-11-03 |
| No new entries once price touches the daily R2 or S2 | Owner, 2026-11-03 |
| Daily CPR histogram Sideways (0.50 to 0.75% wide): no trades that day | Owner, 2026-11-03 |
| Sideways Trading (0.75% and wider): exit at the target MTZ | Owner, 2026-11-03 |
| Trending and Possible Trending (below 0.50%): no target; exit when a candle of the opposite colour closes beyond the 5 EMA | Owner, 2026-11-03 |
| 5- or 15-minute candles | Owner, 2026-11-03 |
| The CPR width thresholds are a backtest option | Owner, 2026-11-03 (3.0.0) |
| The 2-day CPR relationship and opening bias (accepted or rejected) set the day's direction | Owner, 2026-11-03 (3.0.0) |
| Where they give no direction, the side of the CPR a 15-minute candle closes beyond sets it | Owner, 2026-11-03 (3.0.0) |
| Except on Trending and Possible Trending days, once the ADR is complete, trade the opposite direction; ADR decides that day's volatility | Owner, 2026-11-03 (3.0.0) |

## Backtest options

| Option | Choices | Default |
| --- | --- | --- |
| Timeframe | 5 or 15 minutes; 15-minute candles are built from the 5-minute dataset, aligned to 09:15 | 5 minutes |
| Entry patterns | Any of OR, DR, ER, WR | All four |
| Entry MTZ | Daily, weekly or both | Both |
| CPR width thresholds | Trending, Possible Trending and Sideways upper bounds, in percent, rising | 0.25, 0.50, 0.75 (the script's) |
| Day direction | On or off | On |
| ADR trade | On or off | On |
| Strategy | MTZ reversal, Pivot Boss (book; see [pivot-boss.md](pivot-boss.md)) or Hot zone scalp (strategy4; see [hot-zone-scalp.md](hot-zone-scalp.md)) | MTZ reversal |

**Day direction.** The script's opening bias for the daily CPR gives the side:

| Bias | 2-day relationship and open | Trades allowed |
| --- | --- | --- |
| Bull Accept | Higher or higher-overlapping CPR, open above BC | Longs |
| Sell here (rejected) | Higher or higher-overlapping CPR, open below BC | Shorts |
| Bear Accept | Lower or lower-overlapping CPR, open below TC | Shorts |
| Buy here (rejected) | Lower or lower-overlapping CPR, open above TC | Longs |
| Bullish / Bearish Breakout | Inside CPR, open above R1 / below S1 | Longs / shorts |
| Others | Inside CPR opening between S1 and R1, outside CPR, unchanged | Set by the latest 15-minute close above TC (longs) or below BC (shorts); none before that |

**ADR trade.** On Sideways and Sideways Trading days, on the candle where the session's range
(high minus low so far) first reaches the ADR, one trade against the move that completed it: the
candle made the day's new high, so short, or new low, so long. Stop beyond that candle, target the
next MTZ (daily or weekly), exit as a target trade. It is not blocked by R2/S2, day direction or the
Sideways no-trade rule, and it does not need a reversal pattern.

Options are stored with each backtest and included in its input hash. The results page compares
patterns, and the Backtests page compares runs.

Not built yet, by the owner's choice: a 1:2 quick exit, a risk-reward setting, exits at the next
pivot, scalping, and switches to turn the R2/S2 rule or the CPR exits off.

## Decision for each candle

1. **ADR trade**, when chosen, as described above. It is checked first.
2. **BUY:** a long reversal candle of a chosen pattern confirms, the daily CPR is not Sideways,
   price has not touched the daily R2 or S2 today, the candle before the confirming candle
   touched a chosen MTZ, and, with day direction on, the day allows longs. On a Sideways Trading
   day another MTZ must also lie above the close.
3. **SELL:** the same, mirrored.
4. **HOLD:** everything else, with a reason code.

| Code | Meaning |
| --- | --- |
| `OR_LONG`, `DR_SHORT`, ... | Which reversal candles confirmed |
| `AT_DAILY_MTZ`, `AT_WEEKLY_MTZ` | Which zone the signal touched |
| `TARGET_DAILY_MTZ`, `TARGET_WEEKLY_MTZ` | Which zone is the target |
| `EXIT_MTZ_TARGET` | Exit at the target (Sideways Trading CPR, or an ADR trade) |
| `EXIT_EMA_TRAIL` | Trending CPR: no target; exit on the 5 EMA trail |
| `CPR_SIDEWAYS_NO_TRADE` | A signal on a Sideways CPR day |
| `R2_S2_REACHED` | A signal after price touched the daily R2 or S2 |
| `NO_REVERSAL_SIGNAL` | No reversal candle on this bar |
| `REVERSAL_NOT_AT_MTZ` | A reversal candle confirmed away from both zones |
| `NO_TARGET_ZONE` | No other MTZ lies in the trade direction |
| `INVALID_STOP` | The stop would not be beyond the close |
| `CONFLICTING_SIGNALS` | Long and short reversal candles confirmed on the same bar |
| `NO_MTZ_LEVELS` | Not enough daily history for levels |
| `DAY_DIRECTION_OPENING_BIAS`, `DAY_DIRECTION_CPR_BREAK_15M` | Where the day's direction came from |
| `AGAINST_DAY_DIRECTION` | A signal against the day's direction |
| `NO_DAY_DIRECTION` | No bias and no 15-minute close beyond the CPR yet |
| `ADR_COMPLETE`, `ADR_LONG`, `ADR_SHORT` | The ADR trade |
| `ADR_DIRECTION_UNCLEAR` | The candle completing the ADR made both the day's high and low |

The explanation text is assembled only from these codes.

## Choices made where the rules were silent

These are implementation choices, not owner instructions. Each is easy to change.

| Question | Choice | Why |
| --- | --- | --- |
| What does "at an MTZ" mean? | The candle before the confirming candle overlaps the band | Same test the script uses for its labels (`f_isInRange` on TC, BC, PP, or inside the band) |
| Which candle is the signal candle? | The one the script labels: the pattern candle for OR, DR and WR; the confirming candle for ER | Matches what appears on the chart |
| Several patterns on one bar? | Combined; the widest candle sets the stop | Conservative stop |
| Where exactly is the target? | Near edge of the next zone: BC above for longs, TC below for shorts | The trade reaches the zone at its near edge |
| Can the touched zone be the target? | No | The rule is "one MTZ to another" |
| No zone in the trade direction | No trade on Sideways Trading days; Trending days need no target | A target trade must have a target |
| Unchosen patterns | Ignored entirely, still recorded in the candle's context | A disabled pattern cannot block or join a signal |
| Does the candle that touches R2 or S2 block its own signal? | Yes | The touch is known at that candle's close, when the decision is made |
| CPR width not available (no history) | Treated as Sideways Trading, as the script does | No MTZ exists then, so no trade is possible anyway |
| EMA trail exit price | The opposite-colour candle's close | The exit is only known at that close |
| CPR width thresholds | Change only the backtest's histogram, which is also what the stored context and the CPR width breakdown show; the trade direction panel keeps the script's | The panel is context only |
| 15-minute close on a 5-minute backtest | The close of the 5-minute candle ending at :00, :15, :30 or :45 | That is the 15-minute candle's close |
| CPR broken on both sides in one day | The latest 15-minute close beyond the CPR sets the direction; a close back inside keeps it | Follows the most recent break |
| Signal on the candle that breaks the CPR | Allowed in the new direction | The break is known at that candle's close |
| ADR used | The ADR from completed sessions, against the range so far today | No look-ahead |
| ADR trade when a position is open | Lost for the day | One position at a time; the ADR completes once |
| ADR trade with no MTZ beyond the close | Not taken (`NO_TARGET_ZONE`) | It is a target trade |
| ADR trades in the pattern comparison | Listed as "ADR trade" | Compared like a pattern |

Execution (fill price, slippage, same-candle stop and target, the EMA trail exit, end-of-day exit)
belongs to the backtesting engine.

Versions 1.0.0 to 5.0.0 stay saved with their results, but they can no longer be rerun because
the strategy code has changed. Backtests made under 2.0.0 have no threshold, direction or ADR
options stored, and ran with the script's thresholds and neither rule.

## Differences from the script on TradingView

| Script behaviour | Python | Effect on comparison |
| --- | --- | --- |
| "Number of Pivots" (default 5) blanks levels on bars older than that many days, measured from today | No such limit | Raise the setting before exporting |
| ADR %, Cur Range and Remaining use the whole day's final high and low on past bars (`lookahead_on`) | Range so far at each bar | These values differ on past bars by design |
| Weekly, monthly, yearly bars come from TradingView | Built from daily candles, weeks start on Monday | To be checked by the comparison test |

## Behaviours ported as written

- With no levels yet, the CPR width is `na`, so the panel reports "Sideways Trading" and table
  tennis, allowing both directions. It does not gate entries.
- With the default daily setting, "bearish failure" and "bullish failure" can never occur: both
  CPRs are compared against the same day's open, which rules them out.
- EMA 5 and EMA 20 are display only. Their seeding is unverified until the comparison test runs.
- Hot zone breakouts, magnet trades and dashboard setups are recorded as context, not entries.
- The script has no market structure (higher highs, lower lows) logic, so none is calculated.

## Look-ahead protection

Candles are evaluated one at a time. A daily candle reaches the strategy only after its session
ends. Before then, only the session's open is used, plus its high and low on the final bar, when
the session is complete. Tests check that decisions do not change when later data changes.

## Verifying against TradingView

No result can be called accurate until `tests/strategy_parity` passes on real exports. Steps are
in `tests/strategy_parity/fixtures/README.md`. The test compares CPR, Camarilla and EMA values.
Signals are drawn as labels, which TradingView does not export, so they are compared by
inspecting the chart.

## Registering a version

With the API running:

```sh
cd backend
.venv/Scripts/python ../scripts/register_strategy.py --pine ../prompt/strategy.pine --version 1.0.0
```

Each version stores the Pine source, the implementation version, a hash of the strategy code, and
the parameters. A version cannot be changed after a completed backtest uses it.
