"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { BacktestHeader } from "@/components/backtest-header";
import { Button, Card, Empty, ErrorBox, Field, Input, Loading, Select, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { duration, points, signedPoints, time } from "@/lib/format";
import { downloadUrl, get, post, query } from "@/services/client";
import type { BacktestDetail, Page, Report, Trade } from "@/types/api";

const PAGE_SIZE = 100;

export default function TradeExplorerPage() {
  const { id } = useParams<{ id: string }>();
  const backtest = useApi<BacktestDetail>(`/backtests/${id}`);
  const [filters, setFilters] = useState({ side: "", outcome: "", exit_reason: "", start_date: "", end_date: "" });
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [exportState, setExportState] = useState<{ report?: Report; error?: string; busy?: boolean }>({});
  const completed = backtest.data?.status === "completed";
  const trades = useApi<Page<Trade>>(completed ? `/backtests/${id}/trades${query({ ...filters, limit: PAGE_SIZE, offset })}` : null);

  const setFilter = (key: keyof typeof filters, value: string) => {
    setOffset(0);
    setFilters((f) => ({ ...f, [key]: value }));
  };

  async function exportTrades() {
    setExportState({ busy: true });
    try {
      const [report] = await post<Report[]>(`/backtests/${id}/reports`, { categories: ["trades"], formats: ["csv"] });
      setExportState({ report, busy: true });
      for (let i = 0; i < 60; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const reports = await get<Report[]>(`/backtests/${id}/reports`);
        const current = reports.find((r) => r.id === report.id);
        if (current?.status === "completed") {
          window.location.href = downloadUrl(`/backtests/${id}/reports/${report.id}/download`);
          setExportState({ report: current });
          return;
        }
        if (current?.status === "failed") throw new Error(current.error ?? "Report failed");
      }
      throw new Error("The report is still being generated. Find it in the Reports page.");
    } catch (err) {
      setExportState({ error: err instanceof Error ? err.message : String(err) });
    }
  }

  if (backtest.loading && !backtest.data) return <Loading />;
  if (backtest.error || !backtest.data) return <ErrorBox message={backtest.error ?? "Backtest not found"} />;

  return (
    <div className="space-y-4">
      <BacktestHeader backtest={backtest.data} onChange={backtest.reload} />
      {!completed ? (
        <Empty>Trades are available once the backtest has completed.</Empty>
      ) : (
        <Card
          actions={
            <Button variant="secondary" onClick={exportTrades} disabled={exportState.busy}>
              {exportState.busy ? "Preparing CSV…" : "Export all trades (CSV)"}
            </Button>
          }
        >
          {exportState.error && <ErrorBox message={exportState.error} />}
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <Field label="Side">
              <Select value={filters.side} onChange={(e) => setFilter("side", e.target.value)}>
                <option value="">All</option>
                <option value="long">Long</option>
                <option value="short">Short</option>
              </Select>
            </Field>
            <Field label="Outcome">
              <Select value={filters.outcome} onChange={(e) => setFilter("outcome", e.target.value)}>
                <option value="">All</option>
                <option value="win">Winning</option>
                <option value="loss">Losing</option>
                <option value="breakeven">Breakeven</option>
              </Select>
            </Field>
            <Field label="Exit reason">
              <Select value={filters.exit_reason} onChange={(e) => setFilter("exit_reason", e.target.value)}>
                <option value="">All</option>
                {["TARGET", "TARGET_GAP", "STOP_LOSS", "STOP_LOSS_GAP", "EOD_SQUARE_OFF", "SESSION_END_MISSING_DATA", "END_OF_DATA"].map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </Select>
            </Field>
            <Field label="From">
              <Input type="date" value={filters.start_date} onChange={(e) => setFilter("start_date", e.target.value)} />
            </Field>
            <Field label="To">
              <Input type="date" value={filters.end_date} onChange={(e) => setFilter("end_date", e.target.value)} />
            </Field>
          </div>

          {trades.loading && !trades.data ? (
            <Loading />
          ) : trades.error ? (
            <ErrorBox message={trades.error} />
          ) : !trades.data?.items.length ? (
            <Empty>No trades match these filters.</Empty>
          ) : (
            <>
              <Table columns={["#", "Date", "Side", "Entry", "Exit", "Entry price", "Exit price", "Stop", "Target", "Exit reason", "Held", "Net points", ""]}>
                {trades.data.items.map((t) => (
                  <TradeRow key={t.id} trade={t} backtestId={id} expanded={expanded === t.id} onToggle={() => setExpanded(expanded === t.id ? null : t.id)} />
                ))}
              </Table>
              <div className="mt-3 flex items-center justify-between text-sm text-ink-2">
                <span>
                  {offset + 1} to {offset + trades.data.items.length} of {trades.data.total}
                </span>
                <div className="flex gap-2">
                  <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</Button>
                  <Button variant="secondary" disabled={offset + PAGE_SIZE >= trades.data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</Button>
                </div>
              </div>
            </>
          )}
        </Card>
      )}
    </div>
  );
}

function TradeRow({ trade: t, backtestId, expanded, onToggle }: { trade: Trade; backtestId: string; expanded: boolean; onToggle: () => void }) {
  const entry = t.indicators_at_entry as { cpr_daily?: { tc?: number; bc?: number }; adr?: { usage_percent?: number }; ema_slow?: number };
  return (
    <>
      <tr>
        <Td>{t.trade_number}</Td>
        <Td>{t.trading_date}</Td>
        <Td className={t.side === "long" ? "text-gain" : "text-loss"}>{t.side}</Td>
        <Td>{time(t.entry_ts)}</Td>
        <Td>{time(t.exit_ts)}</Td>
        <Td>{points(t.entry_price)}</Td>
        <Td>{points(t.exit_price)}</Td>
        <Td>{points(t.stop_loss)}</Td>
        <Td>{points(t.target)}</Td>
        <Td>{t.exit_reason}</Td>
        <Td>{duration(t.holding_seconds)}</Td>
        <Td className={t.net_points >= 0 ? "font-medium text-gain" : "font-medium text-loss"}>{signedPoints(t.net_points)}</Td>
        <Td>
          <button className="text-xs text-accent hover:underline" onClick={onToggle} aria-expanded={expanded}>
            {expanded ? "Hide" : "Details"}
          </button>
        </Td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={13} className="bg-raised px-3 py-3 text-sm">
            <div className="grid gap-3 md:grid-cols-3">
              <p><span className="text-ink-2">Entry reasons:</span> <span className="font-mono text-xs">{t.decision_reason.join(" ")}</span></p>
              <p><span className="text-ink-2">Regime:</span> {t.market_regime ?? "n/a"}</p>
              <p><span className="text-ink-2">Execution:</span> {String(t.execution_assumptions.execution_method)}, slippage {String(t.execution_assumptions.slippage_points)} pts</p>
              <p><span className="text-ink-2">Daily MTZ at entry:</span> {points(entry.cpr_daily?.bc)} to {points(entry.cpr_daily?.tc)}</p>
              <p><span className="text-ink-2">ADR used at entry:</span> {entry.adr?.usage_percent?.toFixed(0) ?? "n/a"}%</p>
              <p><span className="text-ink-2">EMA 20 at entry:</span> {points(entry.ema_slow)}</p>
            </div>
            <Link className="mt-2 inline-block text-accent hover:underline" href={`/backtests/${backtestId}/chart?trade=${t.id}`}>
              Show on chart
            </Link>
          </td>
        </tr>
      )}
    </>
  );
}
