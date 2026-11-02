"use client";

import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { BacktestHeader } from "@/components/backtest-header";
import { LEVELS, StrategyChart } from "@/components/charts/strategy-chart";
import { Card, Empty, ErrorBox, Field, Input, Loading } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { dateTime, points } from "@/lib/format";
import { query } from "@/services/client";
import type { BacktestDetail, Decision, Page, Trade } from "@/types/api";

function addDays(day: string, days: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function ChartPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ChartView />
    </Suspense>
  );
}

function ChartView() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const backtest = useApi<BacktestDetail>(`/backtests/${id}`);
  const trades = useApi<Page<Trade>>(`/backtests/${id}/trades?limit=5000`);
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [visible, setVisible] = useState<Set<string>>(new Set(["daily_tc", "daily_bc", "weekly_tc", "weekly_bc", "ema20"]));
  const tradeParam = params.get("trade");
  const selectedTrade = trades.data?.items.find((t) => t.id === tradeParam) ?? null;

  // Open on the selected trade's session, else the first trade's, else the first week.
  useEffect(() => {
    if (range || !backtest.data || !trades.data) return;
    const focus = selectedTrade?.trading_date ?? trades.data.items[0]?.trading_date ?? backtest.data.start_date;
    setRange({ start: focus, end: addDays(focus, selectedTrade ? 0 : 4) });
  }, [backtest.data, trades.data, selectedTrade, range]);

  const decisions = useApi<Page<Decision>>(
    range ? `/backtests/${id}/decisions${query({ start_date: range.start, end_date: range.end, limit: 5000 })}` : null,
  );
  const items = useMemo(() => decisions.data?.items ?? [], [decisions.data]);
  const candle = selected !== null ? items[selected] : null;

  if (backtest.loading && !backtest.data) return <Loading />;
  if (backtest.error || !backtest.data) return <ErrorBox message={backtest.error ?? "Backtest not found"} />;
  if (backtest.data.status !== "completed") {
    return (
      <>
        <BacktestHeader backtest={backtest.data} onChange={backtest.reload} />
        <Empty>The chart is available once the backtest has completed.</Empty>
      </>
    );
  }

  return (
    <div className="space-y-4">
      <BacktestHeader backtest={backtest.data} onChange={backtest.reload} />
      <Card>
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <Field label="From">
            <Input type="date" value={range?.start ?? ""} min={backtest.data.start_date} max={backtest.data.end_date}
              onChange={(e) => { setSelected(null); setRange((r) => ({ start: e.target.value, end: r?.end && r.end >= e.target.value ? r.end : e.target.value })); }} />
          </Field>
          <Field label="To">
            <Input type="date" value={range?.end ?? ""} min={range?.start ?? backtest.data.start_date} max={backtest.data.end_date}
              onChange={(e) => { setSelected(null); setRange((r) => (r ? { ...r, end: e.target.value } : r)); }} />
          </Field>
          <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-sm" aria-label="Levels shown">
            {LEVELS.map((level) => (
              <label key={level.key} className="flex items-center gap-1.5 text-ink-2">
                <input
                  type="checkbox"
                  checked={visible.has(level.key)}
                  onChange={() =>
                    setVisible((v) => {
                      const next = new Set(v);
                      if (next.has(level.key)) next.delete(level.key);
                      else next.add(level.key);
                      return next;
                    })
                  }
                />
                <span aria-hidden className="inline-block h-0.5 w-4" style={{ background: level.color, opacity: level.dashed ? 0.6 : 1 }} />
                {level.label}
              </label>
            ))}
          </fieldset>
        </div>
        {decisions.loading && !decisions.data ? (
          <Loading label="Loading candles" />
        ) : decisions.error ? (
          <ErrorBox message={decisions.error} />
        ) : items.length === 0 ? (
          <Empty>No candles in this range.</Empty>
        ) : (
          <>
            {decisions.data && decisions.data.total > items.length && (
              <p className="mb-2 text-xs text-warn">Showing the first {items.length} of {decisions.data.total} candles. Narrow the range.</p>
            )}
            <StrategyChart decisions={items} trades={trades.data?.items ?? []} visibleLevels={visible} selectedTrade={selectedTrade} onSelectCandle={setSelected} />
            <p className="mt-2 text-xs text-muted">
              Times are exchange time (IST). Arrows mark the strategy&apos;s BUY (up) and SELL (down) decisions. Circles mark trade entries with the
              trade number; squares mark exits with net points. Daily levels break between sessions. Click a candle to inspect its decision.
            </p>
          </>
        )}
      </Card>

      <Card title={candle ? `Decision at ${dateTime(candle.candle_ts)}` : "Decision"}>
        {!candle ? (
          <Empty>Click a candle to see the strategy&apos;s decision for it.</Empty>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-2 text-sm">
              <p>
                <span className={candle.action === "BUY" ? "font-semibold text-gain" : candle.action === "SELL" ? "font-semibold text-loss" : "font-semibold"}>
                  {candle.action}
                </span>{" "}
                · position after: {candle.position_state}
              </p>
              <p className="text-ink-2">{candle.explanation}</p>
              <p className="font-mono text-xs text-muted">{candle.reason_codes.join("  ")}</p>
              {(candle.trade_engine_state.execution_notes ?? []).length > 0 && (
                <p className="text-xs text-ink-2">Execution: {(candle.trade_engine_state.execution_notes ?? []).join(", ")}</p>
              )}
            </div>
            <dl className="tabular grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
              <dt className="text-ink-2">Open / High / Low / Close</dt>
              <dd className="text-right">{points(candle.open)} / {points(candle.high)} / {points(candle.low)} / {points(candle.close)}</dd>
              <dt className="text-ink-2">Daily MTZ (BC to TC)</dt>
              <dd className="text-right">{points(candle.market_context.cpr.daily?.bc)} to {points(candle.market_context.cpr.daily?.tc)}</dd>
              <dt className="text-ink-2">Weekly MTZ</dt>
              <dd className="text-right">{points(candle.market_context.cpr.weekly?.bc)} to {points(candle.market_context.cpr.weekly?.tc)}</dd>
              <dt className="text-ink-2">EMA 20</dt>
              <dd className="text-right">{points(candle.market_context.ema20)} ({candle.market_context.ema_direction ?? "n/a"})</dd>
              <dt className="text-ink-2">ADR used</dt>
              <dd className="text-right">{candle.market_context.adr_usage_percent === null ? "n/a" : `${candle.market_context.adr_usage_percent.toFixed(0)}%`}</dd>
              <dt className="text-ink-2">Permission (panel)</dt>
              <dd className="text-right">long {String(candle.long_permission)}, short {String(candle.short_permission)}</dd>
              <dt className="text-ink-2">Regime</dt>
              <dd className="text-right">{candle.market_context.market_regime ?? "n/a"}</dd>
            </dl>
          </div>
        )}
      </Card>
    </div>
  );
}
