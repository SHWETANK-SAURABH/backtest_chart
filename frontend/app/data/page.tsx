"use client";

import { CircleAlert, CircleCheck } from "lucide-react";
import { type FormEvent, Fragment, useState } from "react";

import { Button, Card, Empty, ErrorBox, Field, Input, Loading, PageHeader, Select, StatusBadge, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { count, dateTime, shortId } from "@/lib/format";
import { post } from "@/services/client";
import type { DatasetInfo, IngestionJob, MarketDataHealth } from "@/types/api";

export default function DataManagerPage() {
  const [checkConnection, setCheckConnection] = useState(false);
  const health = useApi<MarketDataHealth>(`/market-data/health${checkConnection ? "?check_connection=true" : ""}`);
  const datasets = useApi<DatasetInfo[]>("/market-data/datasets", 10000);
  const jobs = useApi<IngestionJob[]>("/market-data/jobs?limit=50", 4000);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dataset = datasets.data?.find((d) => d.id === selected) ?? datasets.data?.[0] ?? null;
  // Default the download form to a provider that has a token.
  const providers = health.data?.providers ?? [];
  const configured = (providers.find((p) => p.configured) ?? providers[0])?.code ?? "";

  async function startDownload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(null);
    try {
      await post("/market-data/ingest", {
        provider: form.get("provider"),
        timeframe: form.get("timeframe"),
        start_date: form.get("start_date"),
        end_date: form.get("end_date"),
      });
      jobs.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function jobAction(job: IngestionJob, action: "cancel" | "resume") {
    try {
      await post(`/market-data/jobs/${job.id}/${action}`, {});
      jobs.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Historical data" description="NIFTY 50 spot candles. Every download creates an immutable, versioned dataset." />
      {error && <ErrorBox message={error} />}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="Provider" actions={<Button variant="secondary" onClick={() => setCheckConnection(true)}>Check connection</Button>}>
          {health.loading && !health.data ? (
            <Loading />
          ) : health.error ? (
            <ErrorBox message={health.error} />
          ) : (
            <ul className="space-y-2 text-sm">
              {health.data?.providers.map((p) => {
                const ok = p.configured && p.connected !== false;
                const Icon = ok ? CircleCheck : CircleAlert;
                return (
                  <li key={p.code} className="flex flex-wrap items-center gap-2">
                    <Icon aria-hidden className={ok ? "size-4 text-good" : "size-4 text-warn"} />
                    <span className="font-medium">{p.name}</span>
                    <span className="text-ink-2">
                      {!p.configured ? `No access token (set ${p.code.toUpperCase()}_ACCESS_TOKEN in .env)` : p.detail ?? "Configured; connection not checked"}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card title="Download">
          <form onSubmit={startDownload} className="grid gap-3 sm:grid-cols-2">
            <Field label="Provider">
              <Select name="provider" key={configured} defaultValue={configured}>
                {health.data?.providers.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
              </Select>
            </Field>
            <Field label="Timeframe">
              <Select name="timeframe" defaultValue="5m">
                <option value="5m">5 minutes</option>
                <option value="1d">Daily</option>
              </Select>
            </Field>
            <Field label="From" hint="5-minute history: Upstox from January 2022, Dhan the last 5 years">
              <Input type="date" name="start_date" required />
            </Field>
            <Field label="To">
              <Input type="date" name="end_date" required />
            </Field>
            <Button type="submit" className="sm:col-span-2 sm:w-fit">Start download</Button>
          </form>
        </Card>
      </div>

      <Card title="Dataset versions">
        {datasets.loading && !datasets.data ? (
          <Loading />
        ) : !datasets.data?.length ? (
          <Empty>No datasets yet.</Empty>
        ) : (
          <Table columns={["Timeframe", "Version", "Coverage", "Rows", "Missing candles", "Status", "Created", ""]}>
            {datasets.data.map((d) => (
              <tr key={d.id} className={d.id === dataset?.id ? "bg-raised" : undefined}>
                <Td>{d.timeframe}</Td>
                <Td>v{d.version}</Td>
                <Td>{d.start_date} to {d.end_date}</Td>
                <Td>{count(d.row_count)}</Td>
                <Td>{count(d.quality_report.missing_candles as number)}</Td>
                <Td><StatusBadge status={d.status} /></Td>
                <Td>{dateTime(d.created_at)}</Td>
                <Td><button className="text-xs text-accent hover:underline" onClick={() => setSelected(d.id)}>Quality report</button></Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {dataset && <QualityReport dataset={dataset} />}

      <Card title="Download jobs">
        {!jobs.data?.length ? (
          <Empty>No download jobs yet.</Empty>
        ) : (
          <Table columns={["Job", "Timeframe", "Range", "Progress", "Status", "Created", ""]}>
            {jobs.data.map((j) => {
              const done = (j.progress.completed_chunks as string[] | undefined)?.length ?? 0;
              const total = (j.progress.total_chunks as number | undefined) ?? 0;
              return (
                <tr key={j.id}>
                  <Td className="font-mono text-xs">{shortId(j.id)}</Td>
                  <Td>{j.timeframe}</Td>
                  <Td>{j.start_date} to {j.end_date}</Td>
                  <Td>{total ? `${done} of ${total} chunks` : ""}</Td>
                  <Td>
                    <StatusBadge status={j.status} />
                    {j.error && <p className="max-w-sm text-xs text-critical">{j.error}</p>}
                  </Td>
                  <Td>{dateTime(j.created_at)}</Td>
                  <Td>
                    {(j.status === "pending" || j.status === "running") && <Button variant="ghost" onClick={() => jobAction(j, "cancel")}>Cancel</Button>}
                    {j.status === "failed" && <Button variant="ghost" onClick={() => jobAction(j, "resume")}>Resume</Button>}
                  </Td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>
    </div>
  );
}

function QualityReport({ dataset }: { dataset: DatasetInfo }) {
  const q = dataset.quality_report as Record<string, unknown>;
  const missingByDate = (q.missing_by_date as Record<string, string[]>) ?? {};
  const rows: [string, unknown][] = [
    ["Critical issues", q.has_critical_issues ? "Yes: not usable for backtests" : "None"],
    ["Invalid OHLC", q.invalid_ohlc],
    ["Duplicate timestamps", q.duplicate_timestamps],
    ["Misaligned timestamps", q.misaligned_timestamps],
    ["Bars outside session hours", q.outside_session_bars],
    ["Missing candles", q.missing_candles],
    ["Missing whole sessions", (q.missing_sessions as string[] | undefined)?.length ?? 0],
    ["Sessions not in the calendar", ((q.unscheduled_sessions as string[] | undefined) ?? []).join(", ") || "None"],
    ["Rows with volume", q.rows_with_volume],
    ["Revised candles", q.revised_candles],
    ["Incomplete candles excluded", q.excluded_incomplete_candles],
    ["Holiday calendar verified", q.unverified_calendar_dates ? "No: dates beyond the calendar's coverage" : "Yes"],
  ];
  return (
    <Card title={`Quality report: ${dataset.timeframe} v${dataset.version}`}>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <dl className="tabular grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
          {rows.map(([label, value]) => (
            <Fragment key={label}>
              <dt className="text-ink-2">{label}</dt>
              <dd className="text-right">{String(value ?? 0)}</dd>
            </Fragment>
          ))}
        </dl>
        <div>
          <p className="mb-1 text-sm text-ink-2">Sessions with missing candles</p>
          {Object.keys(missingByDate).length === 0 ? (
            <p className="text-sm">None</p>
          ) : (
            <ul className="max-h-56 space-y-1 overflow-y-auto text-sm">
              {Object.entries(missingByDate).map(([day, times]) => (
                <li key={day}>
                  <span className="tabular">{day}</span>: <span className="text-ink-2">{times.length} missing ({times.slice(0, 6).join(", ")}{times.length > 6 ? "…" : ""})</span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 font-mono text-xs text-muted">Content hash {dataset.content_hash.slice(0, 16)}</p>
        </div>
      </div>
    </Card>
  );
}
