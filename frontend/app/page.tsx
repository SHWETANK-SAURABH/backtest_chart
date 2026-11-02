"use client";

import Link from "next/link";

import { EquityChart } from "@/components/charts/equity-chart";
import { HealthPanel } from "@/components/health-panel";
import { StatTile } from "@/components/stat-tile";
import { Card, Empty, ErrorBox, Loading, PageHeader, PointsNotice, StatusBadge, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { dateTime, shortId, signedPoints } from "@/lib/format";
import type { Backtest, EquityPoint, Health, IngestionJob, MarketDataHealth, Metrics, Overview } from "@/types/api";

export default function OverviewPage() {
  const health = useApi<Health>("/health", 15000);
  const overview = useApi<Overview>("/overview");
  const backtests = useApi<Backtest[]>("/backtests?limit=10", 10000);
  const data = useApi<MarketDataHealth>("/market-data/health");
  const jobs = useApi<IngestionJob[]>("/market-data/jobs?limit=5", 10000);
  const latest = backtests.data?.find((b) => b.status === "completed") ?? null;
  const metrics = useApi<Metrics>(latest ? `/backtests/${latest.id}/metrics` : null);
  const equity = useApi<EquityPoint[]>(latest ? `/backtests/${latest.id}/equity` : null);

  return (
    <div className="space-y-4">
      <PageHeader title="Overview" description={<PointsNotice />} />
      <HealthPanel health={health.data} unreachable={!!health.error} />

      {overview.error ? (
        <ErrorBox message={`Totals are unavailable: ${overview.error}`} />
      ) : (
        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Platform totals">
          <StatTile label="Backtests" value={overview.data?.backtests ?? "…"} />
          <StatTile label="Completed backtests" value={overview.data?.completed_backtests ?? "…"} />
          <StatTile label="Strategy versions" value={overview.data?.strategy_versions ?? "…"} />
          <StatTile label="Dataset versions" value={overview.data?.datasets ?? "…"} />
        </section>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card
          title={latest ? `Latest completed backtest (${latest.start_date} to ${latest.end_date})` : "Latest completed backtest"}
          actions={latest && <Link className="text-sm text-accent hover:underline" href={`/backtests/${latest.id}`}>Open</Link>}
        >
          {!latest ? (
            <Empty>No completed backtest yet.</Empty>
          ) : (
            <>
              <div className="mb-3 grid grid-cols-3 gap-3 text-sm">
                <Figure label="Net points" value={signedPoints(metrics.data?.net_points)} />
                <Figure label="Trades" value={metrics.data?.total_trades?.toString() ?? "…"} />
                <Figure label="Max drawdown" value={metrics.data?.max_drawdown_points?.toFixed(2) ?? "n/a"} />
              </div>
              {equity.data && equity.data.length > 0 ? <EquityChart data={equity.data} /> : <Empty>No trades in this backtest.</Empty>}
            </>
          )}
        </Card>

        <div className="space-y-4">
          <Card title="Historical data" actions={<Link className="text-sm text-accent hover:underline" href="/data">Manage</Link>}>
            {data.loading && !data.data ? (
              <Loading />
            ) : data.error ? (
              <ErrorBox message={data.error} />
            ) : data.data && data.data.datasets.length > 0 ? (
              <Table columns={["Timeframe", "Version", "Coverage", "Rows", "Status"]}>
                {data.data.datasets.map((d) => (
                  <tr key={d.id}>
                    <Td>{d.timeframe}</Td>
                    <Td>v{d.version}</Td>
                    <Td>{d.start_date} to {d.end_date}</Td>
                    <Td>{d.row_count.toLocaleString("en-IN")}</Td>
                    <Td><StatusBadge status={d.status} /></Td>
                  </tr>
                ))}
              </Table>
            ) : (
              <Empty>No market data downloaded yet.</Empty>
            )}
          </Card>

          <Card title="Recent jobs">
            <Table columns={["Job", "Range", "Status", "Created"]}>
              {(backtests.data ?? []).slice(0, 5).map((b) => (
                <tr key={b.id}>
                  <Td><Link className="text-accent hover:underline" href={`/backtests/${b.id}`}>Backtest {shortId(b.id)}</Link></Td>
                  <Td>{b.start_date} to {b.end_date}</Td>
                  <Td><StatusBadge status={b.status} /></Td>
                  <Td>{dateTime(b.created_at)}</Td>
                </tr>
              ))}
              {(jobs.data ?? []).map((j) => (
                <tr key={j.id}>
                  <Td>Download {j.timeframe}</Td>
                  <Td>{j.start_date} to {j.end_date}</Td>
                  <Td><StatusBadge status={j.status} /></Td>
                  <Td>{dateTime(j.created_at)}</Td>
                </tr>
              ))}
            </Table>
            {!backtests.data?.length && !jobs.data?.length && <Empty>No jobs yet.</Empty>}
          </Card>
        </div>
      </div>
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted">{label}</p>
      <p className="tabular text-lg font-semibold">{value}</p>
    </div>
  );
}
