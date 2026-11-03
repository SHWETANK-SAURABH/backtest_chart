"use client";

import Link from "next/link";

import { Card, Empty, ErrorBox, LinkButton, Loading, PageHeader, StatusBadge, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { dateTime, percent, shortId, signedPoints, strategyOptions } from "@/lib/format";
import type { BacktestListItem } from "@/types/api";

export default function BacktestsPage() {
  const { data, error, loading } = useApi<BacktestListItem[]>("/backtests?limit=200", 5000);
  return (
    <div>
      <PageHeader
        title="Backtests"
        description="Compare runs: each row shows its options and headline results."
        actions={<LinkButton href="/backtests/new">New backtest</LinkButton>}
      />
      <Card>
        {loading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorBox message={error} />
        ) : !data?.length ? (
          <Empty>No backtests yet. Create one once market data and a strategy version exist.</Empty>
        ) : (
          <Table columns={["Backtest", "Range", "Timeframe", "Patterns", "MTZ", "Trades", "Win rate", "Net points", "Profit factor", "Status", "Created"]}>
            {data.map((b) => {
              const options = strategyOptions(b);
              const s = b.summary;
              return (
                <tr key={b.id}>
                  <Td><Link className="text-accent hover:underline" href={`/backtests/${b.id}`}>{shortId(b.id)}</Link></Td>
                  <Td>{b.start_date} to {b.end_date}</Td>
                  <Td>{options.timeframe}</Td>
                  <Td>{options.patterns}</Td>
                  <Td>{options.mtz}</Td>
                  <Td>{s ? s.total_trades : ""}</Td>
                  <Td>{s ? percent(s.win_rate) : ""}</Td>
                  <Td className={s ? (s.net_points >= 0 ? "text-gain" : "text-loss") : undefined}>{s ? signedPoints(s.net_points) : ""}</Td>
                  <Td>{s ? (s.profit_factor === null ? "n/a" : s.profit_factor.toFixed(2)) : ""}</Td>
                  <Td>
                    <StatusBadge status={b.status} />
                    {b.error && <p className="max-w-xs truncate text-xs text-critical" title={b.error}>{b.error}</p>}
                  </Td>
                  <Td>{dateTime(b.created_at)}</Td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>
    </div>
  );
}
