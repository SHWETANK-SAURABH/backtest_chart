"use client";

import { CircleAlert, CircleCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button, Card, ErrorBox, StatusBadge, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { dateTime, shortId } from "@/lib/format";
import { post } from "@/services/client";
import type { Backtest, Reproducibility } from "@/types/api";

export function ReproducibilityCard({ backtestId }: { backtestId: string }) {
  const state = useApi<Reproducibility>(`/backtests/${backtestId}/reproducibility`, 5000);
  const [error, setError] = useState<string | null>(null);

  async function rerun() {
    setError(null);
    try {
      await post<Backtest>(`/backtests/${backtestId}/rerun`, {});
      state.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const data = state.data;
  return (
    <Card title="Reproducibility" actions={<Button variant="secondary" onClick={rerun}>Re-run with identical inputs</Button>}>
      {error && <ErrorBox message={error} />}
      {data && (
        <>
          <p className="mb-3 flex items-center gap-2 text-sm">
            {data.identical === null ? (
              <span className="text-ink-2">Re-run to confirm that the same inputs give the same result.</span>
            ) : data.identical ? (
              <>
                <CircleCheck aria-hidden className="size-4 text-good" />
                {data.completed_runs} completed runs with these inputs produced identical results.
              </>
            ) : (
              <>
                <CircleAlert aria-hidden className="size-4 text-critical" />
                Runs with identical inputs produced different results. This needs investigating.
              </>
            )}
          </p>
          <Table columns={["Run", "Status", "Result hash", "Created"]}>
            {data.runs.map((r) => (
              <tr key={r.id}>
                <Td>
                  <Link className="text-accent hover:underline" href={`/backtests/${r.id}`}>{shortId(r.id)}</Link>
                  {r.id === backtestId && <span className="ml-2 text-xs text-muted">this run</span>}
                </Td>
                <Td><StatusBadge status={r.status} /></Td>
                <Td className="font-mono text-xs">{r.result_hash?.slice(0, 16) ?? ""}</Td>
                <Td>{dateTime(r.created_at)}</Td>
              </tr>
            ))}
          </Table>
          <p className="mt-2 font-mono text-xs text-muted">Input hash {data.input_hash.slice(0, 16)}</p>
        </>
      )}
    </Card>
  );
}
