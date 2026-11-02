# MTZ Reversal strategy

The port of the owner's Pine Script indicator, plus the entry rules the owner supplied. The script
itself is kept out of version control. Line numbers below refer to it.

## Source of each rule

The script is an `indicator()`, not a `strategy()`. It calculates levels and draws signals, but
places no trades. The trading rules come from the owner, confirmed on 2026-11-02.

| Rule | Source |
| --- | --- |
| CPR, Camarilla, ADR, EMA, hot zones, trade direction panel | Script, ported exactly |
| Reversal candles OR, DR, ER, WR | Script, lines 1394-1504 |
| Zones are the daily and weekly MTZ (BC to TC) | Owner |
| Enter on a reversal candle at an MTZ | Owner |
| Target the next MTZ in the trade direction | Owner |
| Stop at the signal candle's low (long) or high (short) | Owner |
| Trade direction panel does not gate entries | Owner |

## Decision for each candle

1. **BUY:** a long reversal candle confirms, the candle before the confirming candle touched an MTZ,
   and another MTZ lies above the close.
2. **SELL:** the same, mirrored.
3. **HOLD:** everything else, with a reason code.

| Code | Meaning |
| --- | --- |
| `OR_LONG`, `DR_SHORT`, ... | Which reversal candles confirmed |
| `AT_DAILY_MTZ`, `AT_WEEKLY_MTZ` | Which zone the signal touched |
| `TARGET_DAILY_MTZ`, `TARGET_WEEKLY_MTZ` | Which zone is the target |
| `NO_REVERSAL_SIGNAL` | No reversal candle on this bar |
| `REVERSAL_NOT_AT_MTZ` | A reversal candle confirmed away from both zones |
| `NO_TARGET_ZONE` | No other MTZ lies in the trade direction |
| `INVALID_STOP` | The stop would not be beyond the close |
| `CONFLICTING_SIGNALS` | Long and short reversal candles confirmed on the same bar |
| `NO_MTZ_LEVELS` | Not enough daily history for levels |

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
| No zone in the trade direction | No trade | A trade must have a target |

Execution (fill price, slippage, same-candle stop and target, end-of-day exit) belongs to the
backtesting engine in Phase 4.

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
