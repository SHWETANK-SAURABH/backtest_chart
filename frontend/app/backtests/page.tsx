"use client";

import Link from "next/link";

import { Card, Empty, ErrorBox, LinkButton, Loading, PageHeader, StatusBadge, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { dateTime, shortId } from "@/lib/format";
import type { Backtest } from "@/types/api";

export default function BacktestsPage() {
  const { data, error, loading } = useApi<Backtest[]>("/backtests?limit=200", 5000);
  return (
    <div>
      <PageHeader
        title="Backtests"
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
          <Table columns={["Backtest", "Range", "Execution", "Slippage", "Status", "Created", "Result hash"]}>
            {data.map((b) => (
              <tr key={b.id}>
                <Td><Link className="text-accent hover:underline" href={`/backtests/${b.id}`}>{shortId(b.id)}</Link></Td>
                <Td>{b.start_date} to {b.end_date}</Td>
                <Td>{b.execution_method === "signal_close" ? "Signal close (idealised)" : "Next open"}</Td>
                <Td>{String(b.execution_settings.slippage_points ?? 0)} pts</Td>
                <Td>
                  <StatusBadge status={b.status} />
                  {b.error && <p className="max-w-xs truncate text-xs text-critical" title={b.error}>{b.error}</p>}
                </Td>
                <Td>{dateTime(b.created_at)}</Td>
                <Td className="font-mono text-xs text-muted">{b.result_hash?.slice(0, 12) ?? ""}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
