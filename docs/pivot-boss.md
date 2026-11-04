# Pivot Boss strategy

A second strategy, chosen per backtest with **Strategy: Pivot Boss (book)**. It trades the setups
of *Secrets of a Pivot Boss*, as ported in the owner's `prompt/book.txt` and summarised in
`prompt/mainbook.txt`. Both files are kept out of version control. The code is
`backend/app/strategy/pivot_boss.py` (implementations 4.0.0 and 5.0.0).

## Owner decisions, 2026-11-03

| Question | Decision |
| --- | --- |
| book.txt and the book summary disagree | Follow the book summary |
| Narrow and wide days | The CPR histogram with the backtest's thresholds, as in the MTZ strategy |
| The open rejects the bias | Fade: a reversal candle at the CPR the other way, stop at that candle, target S1/R1 |
| Breakaway exit | Target R3/S3 and a 1.5 ATR trailing stop |
| Floor pivot target | R1/S1 |
| Magnet time exit | None: target the CPR, stop at the day's extreme, otherwise the close |
| Extra setups beyond book.txt | Floor pivot (trend filtered) and magnet |
| Full trend analysis (2026-11-04) | An option on this strategy, gating every setup |
| Seven relationships (2026-11-04) | The book's mapping, below; an opposite opening flips the day |
| Weekly trend with trend analysis (2026-11-04) | Must agree or be neutral |
| Camarilla entries (2026-11-04) | A new setup: the 4 reversal patterns at Camarilla levels, CPR width picks the play |
| S1/R1 trend (2026-11-04) | Part of full trend analysis; must agree or be neutral |
| John Person's trend plan (2026-11-04) | A new setup using the S1/R1 trend; target always R1/S1 |
| Trend-change play (2026-11-04) | A new setup; a strong day closes at a 5-day high (low) with a range of at least the ADR |
| "Wait for a clear trend" (2026-11-04) | A "clear trend only" option: trend setups need all three trends to agree |

## What decides the day

- **Daily bias:** yesterday's close against yesterday's own CPR: above is +1, below is -1,
  inside is 0. Worked out from the daily candles.
- **Open confirms the bias:** for +1, the open is above BC; for -1, below TC. Otherwise the open
  rejects it.
- **Two-day relationship:** Higher or Overlapping Higher Value for longs; Lower or Overlapping
  Lower Value for shorts.
- **Established trend** (floor pivot): the last two daily biases were both +1 (or both -1). This
  is the book's "hold the CPR two consecutive days".
- **Narrow day:** Trending or Possible Trending by the backtest's CPR thresholds. Used by the
  breakaway.
- **Weekly bias** (option, on by default): last week's close against last week's own CPR. Longs
  only when it is 0 or +1, shorts only when 0 or -1. The book: "Trade daily setups only in the
  direction of the weekly trend."

## Full trend analysis (option)

Off by default. When on, a setup trades only if all three checks allow its side, and the weekly
filter above is not used.

**1. The day, from the 7 two-day CPR relationships**

| Relationship | Sides | Opening against it |
| --- | --- | --- |
| Higher Value | Longs | Open below BC: shorts |
| Overlapping Higher Value | Longs; shorts only on a strong signal (2 or more patterns on the candle) | Open below BC: shorts |
| Lower Value | Shorts | Open above TC: longs |
| Overlapping Lower Value | Shorts; longs only on a strong signal | Open above TC: longs |
| Unchanged | The open decides: above TC longs, below BC shorts, inside none | |
| Outside Value | Both (range day) | |
| Inside Value | None until the first 15-minute close beyond the CPR, then that side (breakout day) | |

**2. The floor-pivot trend (S1/R1).** From the daily candles: an uptrend holds while each day
closes at or above that day's S1, and a close below S1 turns it down; a downtrend holds while each
close is at or below R1, and a close above R1 turns it up. Before the first close beyond S1 or R1
it is neutral. The trend must match the setup's side or be neutral.

**3. The weekly trend.** Last week's close against its own CPR (+1, 0, -1) plus the
week-over-week relationship (+1 Higher or Overlapping Higher, -1 Lower or Overlapping Lower, 0
otherwise). A positive sum is up, negative is down, zero is neutral. It must match or be neutral.

Blocked setups are recorded as `AGAINST_DAY_TREND`, `AGAINST_PIVOT_TREND` or
`AGAINST_WEEKLY_TREND`.

## Clear trend only (option)

Off by default. "The market trends only about 30% of the time, so wait for a clear trend." The
trend setups (breakaway, CPR pull-back, Person trend plan, floor pivot, H4/L4 breakout) trade only
when the day's relationship gives exactly their side, and the S1/R1 trend and the weekly trend
both point that way; neutral does not count. Other setups are not affected. Blocked setups are
recorded as `TREND_NOT_CLEAR`. It can be used with or without full trend analysis.

## Setups

Checked in this order on each candle; the first valid one enters at the next open.

| Setup | Entry | Stop | Target |
| --- | --- | --- | --- |
| Breakaway | Narrow day; open beyond the prior high and R1 but not past R2 (mirror for shorts); the first candle tests R1 and closes above | The day's low | R3, with a 1.5 ATR(14) trailing stop |
| Magnet | The script's magnet gap (open beyond the CPR within R2/S2, gap at least 0.15 ADR); a reversal candle toward the CPR closing by 10:15 | The day's extreme | The CPR's near edge |
| Trend change | Yesterday closed at the highest of the last 5 closes and its range was at least the ADR; by 11:15, a wick reversal (WR) whose wick candle reaches TC, closing above TC | The wick candle's low | R1 |
| CPR pull-back | Bias +1, open above BC, Higher Value; a long reversal candle whose signal candle reaches TC, closing above TC, by 11:15 | BC | R1 |
| CPR fade | Bias +1 but the open is at or below BC; a short reversal candle reaching BC and closing below it | The reversal candle's high | S1 |
| Person trend plan | S1/R1 uptrend; a long reversal candle at the CPR (close above TC) or at S1 (close above S1). John Person keeps only S1 and the CPR as buy zones | BC, or the lower of S1 and the candle's low | R1 |
| Floor pivot | Established uptrend; a long reversal candle at the CPR (close above TC) or at S1 (close above S1) | BC, or the lower of S1 and the candle's low | R1 |
| H3/L3 reversal | Bias 0 or +1; a candle wicks through L3 and closes above it, then a candle stays above L3 and closes above the prior close | L4 | H3 |
| Camarilla pattern | Wide day (Sideways or Sideways Trading): a long reversal pattern reaching L3 and closing above it; narrow day: the same at L3, or at L4 (closing above L4) | Wide: L4. Narrow: L4 from L3, L5 from L4 | Wide: H3. Narrow: none, exit on the 5 EMA trail |
| H4/L4 breakout | At least one earlier candle today reached H4 and closed below; then the first close above H4 that is also above those candles' highs | H3 | H5 |

Shorts mirror each row. "Reversal candle" is any of the chosen OR, DR, ER and WR patterns, so the
pattern checkboxes also apply to this strategy.

A setup is skipped when the confirming close is already beyond its stop or target
(`INVALID_STOP`, `NO_ROOM_TO_TARGET`), or when the weekly filter blocks it (`AGAINST_WEEKLY_BIAS`).

## Exits

- Fixed stop and target for every setup but the breakaway, with the same execution rules as the
  MTZ strategy: next-open fills, stop first when both are touched, exit at the session's close.
- Breakaway: after each candle closes, the stop moves to that close minus 1.5 ATR (plus for
  shorts) if that is tighter. A trade stopped after the stop moved exits as `TRAILING_STOP`.
- ATR(14) is the average true range of the last 14 intraday candles, including the previous
  session's, as in book.txt.

## Choices made where neither file is exact

| Question | Choice | Why |
| --- | --- | --- |
| "Early session" for the pull-back | Confirming candle closes by 11:15 | book.txt allows the first 8 bars after the first; on 15-minute candles that is 11:30, two hours is the book's "morning" |
| "First bars" for the magnet | Closes by 10:15 | The book says gap fills usually come within 30 to 60 minutes |
| Breakaway R3 or R4 | R3 | Owner's choice |
| book.txt's "skip reversals on narrow days" | Dropped | Marked as the author's own, not the book's |
| Generic confirmation for H3/L3 | The candle after the wick stays beyond the level and closes beyond the prior close | Taken from the book summary's Camarilla chapter |
| Several setups on one candle | The first in the order above | As book.txt does |
| Money Zone setups (Inside Value breakout, virgin POC) | Not built | They need volume; the NIFTY 50 index has none |
| Strong signal on an Overlapping Value day | Two or more different reversal patterns on the confirming candle | The book says "strong signals" without defining them |
| S1/R1 trend start | Neutral until the first daily close beyond S1 or R1 | It needs a first break to exist |
| Weekly trend | Close bias plus relationship, summed | Both are the book's weekly trend tools |
| Setups without reversal patterns under trend analysis | Never count as a strong signal | They have no pattern to count |
| ADR for the strong day | Includes that day's own range | It is the ADR known the next morning |
| Trend change without WR ticked | Cannot fire | It needs a wick reversal, and the pattern boxes choose which candles count |
| Person plan target | Always R1/S1, even after a big day | Owner's choice |
| Trades per day | Not limited by the strategy | book.txt defaults to 2; set it under Risk on the form |

## Reason codes

| Code | Meaning |
| --- | --- |
| `CPR_PULLBACK_LONG`, `CAM_BREAKOUT_SHORT`, ... | The setup and side |
| `TRIGGER_OR`, ... | The reversal candles that triggered it |
| `TARGET_R1`, `TARGET_H5`, ... | The target level |
| `EXIT_FIXED_TARGET`, `EXIT_ATR_TRAIL`, `EXIT_EMA_TRAIL` | The exit method |
| `AGAINST_DAY_TREND`, `AGAINST_PIVOT_TREND`, `AGAINST_WEEKLY_TREND` | Blocked by full trend analysis |
| `TREND_NOT_CLEAR` | Blocked by clear trend only |
| `NO_BOOK_SETUP`, `NO_LEVELS` | Nothing to do on this candle |
| `AGAINST_WEEKLY_BIAS`, `INVALID_STOP`, `NO_ROOM_TO_TARGET` | A setup fired but was not taken |

The results page lists each setup in the pattern comparison.
