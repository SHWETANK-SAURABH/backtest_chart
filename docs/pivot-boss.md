# Pivot Boss strategy

A second strategy, chosen per backtest with **Strategy: Pivot Boss (book)**. It trades the setups
of *Secrets of a Pivot Boss*, as ported in the owner's `prompt/book.txt` and summarised in
`prompt/mainbook.txt`. Both files are kept out of version control. The code is
`backend/app/strategy/pivot_boss.py` (implementation 4.0.0).

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

## Setups

Checked in this order on each candle; the first valid one enters at the next open.

| Setup | Entry | Stop | Target |
| --- | --- | --- | --- |
| Breakaway | Narrow day; open beyond the prior high and R1 but not past R2 (mirror for shorts); the first candle tests R1 and closes above | The day's low | R3, with a 1.5 ATR(14) trailing stop |
| Magnet | The script's magnet gap (open beyond the CPR within R2/S2, gap at least 0.15 ADR); a reversal candle toward the CPR closing by 10:15 | The day's extreme | The CPR's near edge |
| CPR pull-back | Bias +1, open above BC, Higher Value; a long reversal candle whose signal candle reaches TC, closing above TC, by 11:15 | BC | R1 |
| CPR fade | Bias +1 but the open is at or below BC; a short reversal candle reaching BC and closing below it | The reversal candle's high | S1 |
| Floor pivot | Established uptrend; a long reversal candle at the CPR (close above TC) or at S1 (close above S1) | BC, or the lower of S1 and the candle's low | R1 |
| H3/L3 reversal | Bias 0 or +1; a candle wicks through L3 and closes above it, then a candle stays above L3 and closes above the prior close | L4 | H3 |
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
| Trades per day | Not limited by the strategy | book.txt defaults to 2; set it under Risk on the form |

## Reason codes

| Code | Meaning |
| --- | --- |
| `CPR_PULLBACK_LONG`, `CAM_BREAKOUT_SHORT`, ... | The setup and side |
| `TRIGGER_OR`, ... | The reversal candles that triggered it |
| `TARGET_R1`, `TARGET_H5`, ... | The target level |
| `EXIT_FIXED_TARGET`, `EXIT_ATR_TRAIL` | The exit method |
| `NO_BOOK_SETUP`, `NO_LEVELS` | Nothing to do on this candle |
| `AGAINST_WEEKLY_BIAS`, `INVALID_STOP`, `NO_ROOM_TO_TARGET` | A setup fired but was not taken |

The results page lists each setup in the pattern comparison.
