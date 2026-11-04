# Hot zone scalp strategy

A third strategy, chosen per backtest with **Strategy: Hot zone scalp (strategy4)**. It trades
the hot zones that `prompt/strategy4.txt` adds to the owner's indicator: a reversal candle in the
direction of the nearest zone, with a quick exit. The script is kept out of version control. The
code is `backend/app/strategy/hot_zone_scalp.py` (implementation 6.0.0).

## Owner decisions, 2026-11-04

| Question | Decision |
| --- | --- |
| When is price "at" a zone? | As the script is written: the zone nearest the close, however far away |
| Which zones trade | A choice per backtest; MTF confluence and Golden Pivot Zones by default |
| Exit ("quick exit" in the script) | Target the next pivot level beyond the close; stop at the signal candle |
| Trade direction panel | An option: also require the panel's own permission |

## Zones (strategy4.txt lines 555-769)

The backtest uses the daily chart, so the day is the anchor and the week, month and year are the
other timeframes. Two levels are "near" when they are within the hot zone tolerance (0.25% of
price by default).

| Type | Zone | Price | Direction |
| --- | --- | --- | --- |
| MTF confluence | Each of the day's PP, TC, BC, R1, R2, S1, S2, H3, H4, H5, L3, L4, L5. Score 1, plus 1 for each other timeframe with any of its 13 levels near. Kept at or above the minimum score (2, 3 or 4; the script defaults to 2). A zone within tolerance of an earlier one merges into it if it scores higher | The level | Bull for PP, TC, R1, R2, H3-H5; bear for BC, S1, S2, L3-L5 |
| Golden Pivot Zone | TC, BC or PP near Camarilla H3 or L3 of the same timeframe, for the day, week and month | Midpoint | Bull with H3, bear with L3 |
| Double Pivot Zone | R2 near H4, or S2 near L4, for the day, week and month | Midpoint | Bull at R2/H4, bear at S2/L4 |
| MTF star | The day's R1 near the week's PP or TC or the top timeframe's PP or TC (bull); S1 near PP or BC (bear). The top timeframe is the year when it has levels | R1 or S1 | As stated |
| PP/CC | A timeframe's pivot near its Camarilla centre, for all four | Midpoint | Always bull, as in the script |

Named zones score 3 and are always kept.

## Entry and exit

1. On each candle, the chosen zone nearest the close sets the side: bull zone long, bear zone
   short (`f_trade_direction`, lines 1022-1041).
2. A chosen reversal candle (OR, DR, ER or WR) in that direction enters at the next open.
3. With the panel gate on, the trade direction panel must allow that side from its structure,
   gap or PDH/PDL rules; the zone's own permission does not count.
4. Stop: the signal candle's low (long) or high (short).
5. Target: the nearest daily CPR (PP, TC, BC, R1-R4, S1-S4) or Camarilla (H3-H6, L3-L6) level
   beyond the confirming close.
6. Otherwise the trade exits at the session's close. Execution rules are those of the other
   strategies.

## Choices made where the script is silent

| Question | Choice | Why |
| --- | --- | --- |
| Which levels can be targets | CPR and Camarilla H3-H6/L3-L6; not H1, H2, L1, L2, PDH or PDL | The script's zones and labels use these |
| Several reversal candles on one bar | Only those in the zone's direction count; the widest sets the stop | As in the MTZ strategy |
| MTZ rules (R2/S2, Sideways days) | Not applied | They belong to the MTZ strategy |
| The script's hot zones panel | Not ported | Display only |

## Reason codes

| Code | Meaning |
| --- | --- |
| `HZ_MTF_LONG`, `HZ_GPZ_SHORT`, ... | The zone type and side |
| `TRIGGER_OR`, ... | The reversal candles that triggered it |
| `TARGET_H3`, `TARGET_R1`, ... | The target level |
| `NO_HOT_ZONE` | No zone of a chosen type today |
| `SIGNAL_AGAINST_ZONE` | A reversal candle against the nearest zone's direction |
| `PANEL_BLOCKS_DIRECTION` | The panel gate is on and the panel does not allow the side |
| `NO_TARGET_LEVEL`, `INVALID_STOP` | No level beyond the close, or the stop is not beyond it |

Each zone type has its own row in the results page's pattern comparison.
