"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { BacktestHeader } from "@/components/backtest-header";
import { EquityChart } from "@/components/charts/equity-chart";
import { PeriodBars } from "@/components/charts/period-bars";
import { ReproducibilityCard } from "@/components/reproducibility-card";
import { StatTile } from "@/components/stat-tile";
import { Card, Empty, ErrorBox, Loading, Select, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { dateTime, duration, percent, points, signedPoints } from "@/lib/format";
import type { BacktestDetail, EquityPoint, Metrics, PeriodRow } from "@/types/api";

const CATEGORY_LABELS: Record<string, string> = {
  trend: "Trend",
  volatility: "Volatility",
  gap: "Opening gap",
  session_part: "Part of session",
  hour: "Hour",
  weekday: "Weekday",
  adr_usage: "ADR used",
  cpr_width: "CPR width",
  setup: "Reversal pattern",
  opening_bias: "Opening bias",
  day_direction: "Day direction from",
  exit_reason: "Exit reason",
};

const PATTERN_NAMES: Record<string, string> = {
  OR: "Outside reversal (OR)",
  DR: "Doji reversal (DR)",
  ER: "Extreme reversal (ER)",
  WR: "Wick reversal (WR)",
  ADR: "ADR trade",
};

export default function BacktestResultsPage() {
  const { id } = useParams<{ id: string }>();
  const backtest = useApi<BacktestDetail>(`/backtests/${id}`, 4000);
  const completed = backtest.data?.status === "completed";
  const metrics = useApi<Metrics>(completed ? `/backtests/${id}/metrics` : null);
  const equity = useApi<EquityPoint[]>(completed ? `/backtests/${id}/equity` : null);
  const daily = useApi<PeriodRow[]>(completed ? `/backtests/${id}/daily` : null);
  const monthly = useApi<PeriodRow[]>(completed ? `/backtests/${id}/monthly` : null);
  const [category, setCategory] = useState("trend");

  if (backtest.loading && !backtest.data) return <Loading />;
  if (backtest.error || !backtest.data) return <ErrorBox message={backtest.error ?? "Backtest not found"} />;
  const m = metrics.data;

  return (
    <div className="space-y-4">
      <BacktestHeader backtest={backtest.data} onChange={backtest.reload} />
      {!completed ? (
        <Card title="Progress">
          <ul className="space-y-1 text-sm">
            {backtest.data.events.map((e, i) => (
              <li key={i} className="flex gap-3">
                <span className="tabular text-muted">{dateTime(e.at)}</span>
                <span>{e.message ?? e.type}</span>
              </li>
            ))}
          </ul>
          {backtest.data.status === "pending" && <p className="mt-2 text-sm text-ink-2">Waiting for a backtest worker.</p>}
        </Card>
      ) : !m ? (
        metrics.error ? <ErrorBox message={metrics.error} /> : <Loading />
      ) : (
        <>
          <section aria-label="Headline results" className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="Net points" value={signedPoints(m.net_points)} hint={`${m.total_trades} trades`} />
            <StatTile label="Win rate" value={percent(m.win_rate)} hint={`${m.winning_trades} won, ${m.losing_trades} lost`} />
            <StatTile label="Profit factor" value={m.profit_factor === null ? "n/a" : m.profit_factor.toFixed(2)} hint={m.profit_factor === null ? "No losing trades" : undefined} />
            <StatTile label="Max drawdown" value={m.max_drawdown_points === null ? "n/a" : `${points(m.max_drawdown_points)} pts`} />
          </section>

          <Card title="Cumulative points and drawdown">
            {equity.data?.length ? <EquityChart data={equity.data} /> : <Empty>No trades, so no curve.</Empty>}
          </Card>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card title="Monthly net points">
              {monthly.data?.length ? <PeriodBars data={monthly.data} monthly label="Net points per month" /> : <Empty>No data.</Empty>}
            </Card>
            <Card title="Daily net points">
              {daily.data?.length ? <PeriodBars data={daily.data} label="Net points per session" /> : <Empty>No data.</Empty>}
            </Card>
          </div>

          <Card title="Entry pattern comparison">
            {m.by_market_condition.setup ? (
              <Table columns={["Pattern", "Trades", "Win rate", "Won / lost", "Net points", "Average"]}>
                {Object.entries(m.by_market_condition.setup).map(([pattern, s]) => (
                  <tr key={pattern}>
                    <Td>{PATTERN_NAMES[pattern] ?? pattern}</Td>
                    <Td>{s.trades}</Td>
                    <Td>{percent(s.win_rate)}</Td>
                    <Td>{s.wins} / {s.losses}</Td>
                    <Td className={s.net_points >= 0 ? "text-gain" : "text-loss"}>{signedPoints(s.net_points)}</Td>
                    <Td>{signedPoints(s.average_points)}</Td>
                  </tr>
                ))}
              </Table>
            ) : (
              <Empty>No trades to compare.</Empty>
            )}
            <p className="mt-3 text-xs text-muted">
              A trade counts under every pattern that confirmed on its signal candle. To compare patterns on their own, run one backtest per pattern and compare them on the Backtests page.
            </p>
          </Card>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card title="Trade statistics">
              <dl className="tabular grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                <Stat label="Gross profit" value={`${points(m.gross_profit_points)} pts`} />
                <Stat label="Gross loss" value={`${points(m.gross_loss_points)} pts`} />
                <Stat label="Average trade" value={`${signedPoints(m.average_trade_points)} pts`} />
                <Stat label="Expectancy" value={`${signedPoints(m.expectancy_points)} pts`} />
                <Stat label="Average win" value={`${signedPoints(m.average_win_points)} pts`} />
                <Stat label="Average loss" value={`${signedPoints(m.average_loss_points)} pts`} />
                <Stat label="Longest winning run" value={String(m.max_consecutive_wins)} />
                <Stat label="Longest losing run" value={String(m.max_consecutive_losses)} />
                <Stat label="Average holding" value={duration(m.average_holding_seconds)} />
                <Stat label="Sharpe ratio" value={m.sharpe_ratio === null ? "n/a" : m.sharpe_ratio.toFixed(2)} />
              </dl>
              <p className="mt-3 text-xs text-muted">
                Sharpe: {String(m.sharpe_assumptions.series)}; {String(m.sharpe_assumptions.annualisation)}; risk-free rate{" "}
                {String(m.sharpe_assumptions.risk_free_rate)}.
              </p>
            </Card>

            <Card
              title="Performance by market condition"
              actions={
                <Select aria-label="Condition" value={category} onChange={(e) => setCategory(e.target.value)}>
                  {Object.keys(m.by_market_condition).map((c) => (
                    <option key={c} value={c}>{CATEGORY_LABELS[c] ?? c}</option>
                  ))}
                </Select>
              }
            >
              {m.by_market_condition[category] ? (
                <Table columns={["Label", "Trades", "Win rate", "Net points", "Average"]}>
                  {Object.entries(m.by_market_condition[category]).map(([label, s]) => (
                    <tr key={label}>
                      <Td>{label}</Td>
                      <Td>{s.trades}</Td>
                      <Td>{percent(s.win_rate)}</Td>
                      <Td className={s.net_points >= 0 ? "text-gain" : "text-loss"}>{signedPoints(s.net_points)}</Td>
                      <Td>{signedPoints(s.average_points)}</Td>
                    </tr>
                  ))}
                </Table>
              ) : (
                <Empty>No trades to break down.</Empty>
              )}
              <p className="mt-3 text-xs text-muted">Labels use only information known when each entry was decided. See docs/analytics.md.</p>
            </Card>
          </div>
          <ReproducibilityCard backtestId={id} />
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-ink-2">{label}</dt>
      <dd className="text-right">{value}</dd>
    </>
  );
}
