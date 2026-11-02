"use client";

import { CircleAlert, CircleCheck } from "lucide-react";
import { type FormEvent, useState } from "react";

import { DistributionBars } from "@/components/charts/distribution-bars";
import { Button, Card, Empty, ErrorBox, Field, Input, Loading, PageHeader, Select, StatusBadge, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { bytes, count, dateTime, shortId } from "@/lib/format";
import { downloadUrl, get, post } from "@/services/client";
import type { AiDatasetExport, AiDatasetVersion, Backtest } from "@/types/api";

export default function AiDatasetCentrePage() {
  const versions = useApi<AiDatasetVersion[]>("/ai-datasets", 4000);
  const backtests = useApi<Backtest[]>("/backtests?limit=200");
  const completed = (backtests.data ?? []).filter((b) => b.status === "completed");
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const version = versions.data?.find((v) => v.id === selected) ?? versions.data?.[0] ?? null;

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(null);
    try {
      const created = await post<AiDatasetVersion>("/ai-datasets/generate", {
        name: form.get("name"),
        backtest_id: form.get("backtest_id"),
        parameters: {
          train_ratio: Number(form.get("train_ratio")),
          validation_ratio: Number(form.get("validation_ratio")),
          forward_horizons: String(form.get("horizons")).split(",").map((h) => Number(h.trim())).filter(Boolean),
        },
      });
      setSelected(created.id);
      versions.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="AI datasets"
        description="Versioned training data built from completed backtests. Features are decision-time only; outcomes are labels."
      />
      {error && <ErrorBox message={error} />}

      <Card title="Generate a dataset version">
        {completed.length === 0 ? (
          <Empty>Datasets need a completed backtest.</Empty>
        ) : (
          <form onSubmit={generate} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Field label="Dataset name">
              <Input name="name" required defaultValue="mtz-reversal" maxLength={128} />
            </Field>
            <Field label="Backtest">
              <Select name="backtest_id">
                {completed.map((b) => <option key={b.id} value={b.id}>{shortId(b.id)} · {b.start_date} to {b.end_date}</option>)}
              </Select>
            </Field>
            <Field label="Train share" hint="Earliest sessions">
              <Input name="train_ratio" type="number" min={0.05} max={0.9} step={0.05} defaultValue={0.7} />
            </Field>
            <Field label="Validation share" hint="Test gets the rest">
              <Input name="validation_ratio" type="number" min={0.05} max={0.5} step={0.05} defaultValue={0.15} />
            </Field>
            <Field label="Forward horizons (candles)">
              <Input name="horizons" defaultValue="1, 3, 6" />
            </Field>
            <Button type="submit" className="sm:w-fit">Generate</Button>
          </form>
        )}
      </Card>

      <Card title="Dataset versions">
        {versions.loading && !versions.data ? (
          <Loading />
        ) : !versions.data?.length ? (
          <Empty>No datasets yet.</Empty>
        ) : (
          <Table columns={["Dataset", "Version", "Records", "Backtest", "Validation", "Status", "Created"]}>
            {versions.data.map((v) => (
              <tr key={v.id} className={v.id === version?.id ? "bg-raised" : undefined}>
                <Td><button className="text-accent hover:underline" onClick={() => setSelected(v.id)}>{v.dataset_name}</button></Td>
                <Td>{v.version}</Td>
                <Td>{count(v.record_count)}</Td>
                <Td className="font-mono text-xs">{shortId(v.backtest_job_id)}</Td>
                <Td>{v.validation_report.passed === undefined ? "" : v.validation_report.passed ? "Passed" : "Failed"}</Td>
                <Td>
                  <StatusBadge status={v.status} />
                  {v.error && <p className="max-w-xs text-xs text-critical">{v.error}</p>}
                </Td>
                <Td>{dateTime(v.created_at)}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {version && <VersionDetail version={version} />}
    </div>
  );
}

function VersionDetail({ version }: { version: AiDatasetVersion }) {
  const exports = useApi<AiDatasetExport[]>(version.status === "completed" ? `/ai-datasets/${version.id}/exports` : null);
  const [revalidation, setRevalidation] = useState<{ passed: boolean; detail: string } | null>(null);
  const splits = version.split_statistics;

  async function revalidate() {
    const report = await get<{ passed: boolean; files?: string[] }>(`/ai-datasets/${version.id}/validate`);
    setRevalidation({ passed: report.passed, detail: report.files?.length ? report.files.join(", ") : "files, rules and content hash" });
  }

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <Card title={`${version.dataset_name} ${version.version}: splits`}>
        <Table columns={["Split", "Records", "Sessions", "First", "Last"]}>
          {["train", "validation", "test"].map((s) => (
            <tr key={s}>
              <Td>{s}</Td>
              <Td>{count(splits[s]?.records)}</Td>
              <Td>{count(splits[s]?.sessions)}</Td>
              <Td>{splits[s]?.first_session ?? ""}</Td>
              <Td>{splits[s]?.last_session ?? ""}</Td>
            </tr>
          ))}
        </Table>
        <p className="mt-2 text-xs text-muted">Whole sessions in time order; a session never spans two splits.</p>
        <p className="mt-1 font-mono text-xs text-muted">Content hash {version.content_hash?.slice(0, 16) ?? "n/a"}</p>
      </Card>

      <Card title="Data quality" actions={version.status === "completed" && <Button variant="secondary" onClick={revalidate}>Re-validate files</Button>}>
        <ul className="space-y-1 text-sm">
          {(version.validation_report.checks ?? []).map((c) => (
            <li key={c.check} className="flex items-center gap-2">
              {c.passed ? <CircleCheck aria-hidden className="size-4 text-good" /> : <CircleAlert aria-hidden className="size-4 text-critical" />}
              <span>{c.check.replaceAll("_", " ")}</span>
              <span className="text-ink-2">{c.passed ? "passed" : `${c.count} problem${c.count === 1 ? "" : "s"}`}</span>
            </li>
          ))}
        </ul>
        {revalidation && (
          <p className={`mt-3 text-sm ${revalidation.passed ? "text-good" : "text-critical"}`}>
            Re-validation {revalidation.passed ? "passed" : "failed"}: {revalidation.detail}
          </p>
        )}
      </Card>

      <Card title="Decision labels">
        {version.label_distribution.action ? <DistributionBars counts={version.label_distribution.action} label="Records per decision label" /> : <Empty>No labels.</Empty>}
      </Card>
      <Card title="Setup outcomes">
        {version.label_distribution.setup_outcome ? <DistributionBars counts={version.label_distribution.setup_outcome} label="Records per setup outcome" /> : <Empty>No labels.</Empty>}
      </Card>

      <Card title="Exports" className="xl:col-span-2">
        {!exports.data?.length ? (
          <Empty>{version.status === "completed" ? "Loading exports" : "Exports appear once the dataset is complete and valid."}</Empty>
        ) : (
          <Table columns={["Split", "Format", "Records", "Size", "SHA-256", ""]}>
            {exports.data.map((e) => (
              <tr key={e.id}>
                <Td>{e.split}</Td>
                <Td>{e.format.toUpperCase()}</Td>
                <Td>{count(e.record_count)}</Td>
                <Td>{bytes(e.file_size_bytes)}</Td>
                <Td className="font-mono text-xs">{e.sha256.slice(0, 16)}</Td>
                <Td><a className="text-accent hover:underline" href={downloadUrl(`/ai-datasets/${version.id}/exports/${e.id}/download`)}>Download</a></Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
