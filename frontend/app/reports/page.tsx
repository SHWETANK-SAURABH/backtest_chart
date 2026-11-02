"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Button, Card, Empty, ErrorBox, Field, Loading, PageHeader, PointsNotice, Select, StatusBadge, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { bytes, dateTime, shortId } from "@/lib/format";
import { downloadUrl, post } from "@/services/client";
import type { Backtest, Report } from "@/types/api";

const CATEGORIES = [
  { value: "performance", label: "Performance" },
  { value: "trades", label: "Trades" },
  { value: "decisions", label: "Strategy decisions (every candle)" },
  { value: "market_behaviour", label: "Market behaviour" },
];
const FORMATS = ["pdf", "csv", "json", "parquet"];

export default function ReportsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ReportsCentre />
    </Suspense>
  );
}

function ReportsCentre() {
  const router = useRouter();
  const params = useSearchParams();
  const backtests = useApi<Backtest[]>("/backtests?limit=200");
  const completed = (backtests.data ?? []).filter((b) => b.status === "completed");
  const selected = params.get("backtest") ?? completed[0]?.id ?? null;
  const reports = useApi<Report[]>(selected ? `/backtests/${selected}/reports` : null, 3000);
  const [categories, setCategories] = useState<Set<string>>(new Set(["performance"]));
  const [formats, setFormats] = useState<Set<string>>(new Set(["pdf"]));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const toggle = (set: Set<string>, value: string) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  };

  async function generate() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      await post(`/backtests/${selected}/reports`, { categories: [...categories], formats: [...formats] });
      reports.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Reports" description={<>Every report records the backtest, strategy and dataset versions and its execution assumptions. <PointsNotice /></>} />
      {backtests.loading && !backtests.data ? (
        <Loading />
      ) : completed.length === 0 ? (
        <Card><Empty>Reports need a completed backtest.</Empty></Card>
      ) : (
        <>
          <Card title="Generate">
            {error && <ErrorBox message={error} />}
            <div className="grid gap-4 md:grid-cols-3">
              <Field label="Backtest">
                <Select value={selected ?? ""} onChange={(e) => router.replace(`/reports?backtest=${e.target.value}`)}>
                  {completed.map((b) => (
                    <option key={b.id} value={b.id}>{shortId(b.id)} · {b.start_date} to {b.end_date}</option>
                  ))}
                </Select>
              </Field>
              <fieldset className="text-sm">
                <legend className="mb-1 text-ink-2">Reports</legend>
                {CATEGORIES.map((c) => (
                  <label key={c.value} className="flex items-center gap-2">
                    <input type="checkbox" checked={categories.has(c.value)} onChange={() => setCategories(toggle(categories, c.value))} />
                    {c.label}
                  </label>
                ))}
              </fieldset>
              <fieldset className="text-sm">
                <legend className="mb-1 text-ink-2">Formats</legend>
                {FORMATS.map((f) => (
                  <label key={f} className="flex items-center gap-2">
                    <input type="checkbox" checked={formats.has(f)} onChange={() => setFormats(toggle(formats, f))} />
                    {f.toUpperCase()}
                  </label>
                ))}
              </fieldset>
            </div>
            <Button className="mt-4" onClick={generate} disabled={busy || !categories.size || !formats.size}>
              Generate {categories.size * formats.size} report{categories.size * formats.size === 1 ? "" : "s"}
            </Button>
            <p className="mt-2 text-xs text-muted">PDFs show at most 500 rows per table; CSV and Parquet contain every row and column.</p>
          </Card>

          <Card title="Generated reports">
            {reports.error ? (
              <ErrorBox message={reports.error} />
            ) : !reports.data?.length ? (
              <Empty>No reports for this backtest yet.</Empty>
            ) : (
              <Table columns={["Report", "Format", "Status", "Size", "Requested", ""]}>
                {reports.data.map((r) => (
                  <tr key={r.id}>
                    <Td>{CATEGORIES.find((c) => c.value === r.category)?.label ?? r.category}</Td>
                    <Td>{r.format.toUpperCase()}</Td>
                    <Td>
                      <StatusBadge status={r.status} />
                      {r.error && <p className="text-xs text-critical">{r.error}</p>}
                    </Td>
                    <Td>{bytes(r.file_size_bytes)}</Td>
                    <Td>{dateTime(r.created_at)}</Td>
                    <Td>
                      {r.status === "completed" && (
                        <a className="text-accent hover:underline" href={downloadUrl(`/backtests/${r.backtest_job_id}/reports/${r.id}/download`)}>
                          Download
                        </a>
                      )}
                    </Td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
