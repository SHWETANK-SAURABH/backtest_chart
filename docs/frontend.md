# Dashboard

Next.js, React, TypeScript and Tailwind CSS. Charts use TradingView Lightweight Charts (candles)
and Apache ECharts (analytics). Every figure comes from the API; nothing is hardcoded.

## Pages

| Page | Path | Shows |
| --- | --- | --- |
| Overview | `/` | System status, totals, latest completed backtest with its curve, data status, recent jobs |
| Backtests | `/backtests` | Every backtest with status, execution method and result hash |
| New backtest | `/backtests/new` | Strategy version, dates within the 5-minute dataset, entry fill, slippage, risk limits, capital |
| Results | `/backtests/{id}` | Headline figures, cumulative points and drawdown, monthly and daily points, trade statistics, performance by market condition |
| Chart | `/backtests/{id}/chart` | Candles with daily and weekly MTZ, Camarilla levels and EMA 20; BUY and SELL decisions; trade entries and exits; a selected trade's entry, stop and target; click a candle to see its decision |
| Trades | `/backtests/{id}/trades` | Filter by side, outcome, exit reason and date; details per trade; open a trade on the chart; export all trades as CSV |
| Historical data | `/data` | Provider status and connection check, downloads, dataset versions, quality reports, jobs with cancel and resume |
| Strategies | `/strategies` | Versions, entry rules, indicator settings, comparison of two versions and their latest results |
| Reports | `/reports` | Generate any report category in any format, status, downloads |
| AI datasets | `/ai-datasets` | Generate versions, record counts, splits, validation checks, label distributions, re-validation, export downloads |

## Notes

- Times are exchange time (IST). Lightweight Charts labels its axis in UTC, so candle times are
  shifted by the IST offset for display only.
- Pages poll while jobs run, so status updates without a reload.
- The interface is dark only. Chart colours follow a colour-blind-checked palette: gains blue, losses
  red, and level lines in a fixed order with a legend.
- The browser calls the API at `NEXT_PUBLIC_API_BASE_URL`, which is fixed when the frontend is built.
  Credentials never reach the browser.

## Checking the pages

The pages were rendered in Chromium against a throwaway database of synthetic data, at desktop and
phone widths, and checked for console errors and horizontal overflow. Playwright and its browser
were installed only in the project's virtual environment and `.playwright/`, which is not committed.
