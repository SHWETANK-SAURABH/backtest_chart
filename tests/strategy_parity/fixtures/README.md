# TradingView exports for parity tests

Exports are market data and are not committed (`*.csv` is ignored here).

For each comparison, save two files with the same prefix:

1. `<name>_5m.csv`: a NIFTY 50 5-minute chart with the indicator applied.
2. `<name>_1d.csv`: a NIFTY 50 daily chart covering at least two weeks before the 5-minute range.

Before exporting the 5-minute chart, open the indicator settings and raise **Number of Pivots**
well above the number of days in the chart, for example 2000. At the default of 5, levels are
blank on bars older than 5 days.

Export with **Chart menu > Export chart data**, with time format **UNIX timestamp**. The plot
titles in the export (`TC`, `PP`, `Cam-H3`, `EMA 2` and so on) are matched by name.

Run with `backend/.venv/Scripts/python -m pytest tests/strategy_parity`.
