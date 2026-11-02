"use client";

import { useEffect, useMemo, useState } from "react";

import { Card, Empty, ErrorBox, Field, Loading, PageHeader, Select, Table, Td } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { dateTime, percent, signedPoints } from "@/lib/format";
import { get } from "@/services/client";
import type { Backtest, Metrics, Strategy, StrategyDetail, StrategyVersion } from "@/types/api";

type Version = StrategyVersion & { strategy: string };

export default function StrategyExplorerPage() {
  const strategies = useApi<Strategy[]>("/strategies");
  const backtests = useApi<Backtest[]>("/backtests?limit=200");
  const [versions, setVersions] = useState<Version[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [compare, setCompare] = useState<string | null>(null);

  useEffect(() => {
    if (!strategies.data) return;
    Promise.all(strategies.data.map((s) => get<StrategyDetail>(`/strategies/${s.id}`)))
      .then((details) => setVersions(details.flatMap((d) => d.versions.map((v) => ({ ...v, strategy: d.name })))))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [strategies.data]);

  const current = versions.find((v) => v.id === selected) ?? versions[0] ?? null;
  const other = versions.find((v) => v.id === compare) ?? null;

  if ((strategies.loading && !strategies.data) || strategies.error) {
    return strategies.error ? <ErrorBox message={strategies.error} /> : <Loading />;
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Strategies" description="Versions are immutable once a completed backtest uses them." />
      {error && <ErrorBox message={error} />}
      {versions.length === 0 ? (
        <Card>
          <Empty>No strategy version registered. Run scripts/register_strategy.py with the Pine Script file.</Empty>
        </Card>
      ) : (
        <>
          <Card title="Versions">
            <Table columns={["Strategy", "Version", "Implementation", "Code hash", "Pine source", "Created", "Change"]}>
              {versions.map((v) => (
                <tr key={v.id} className={v.id === current?.id ? "bg-raised" : undefined}>
                  <Td><button className="text-accent hover:underline" onClick={() => setSelected(v.id)}>{v.strategy}</button></Td>
                  <Td>{v.version}</Td>
                  <Td>{v.python_implementation_version}</Td>
                  <Td className="font-mono text-xs">{v.code_hash.slice(0, 12)}</Td>
                  <Td className="text-xs">{v.pine_source_reference ?? "n/a"} {v.pine_source_sha256 && <span className="font-mono text-muted">({v.pine_source_sha256.slice(0, 8)})</span>}</Td>
                  <Td>{dateTime(v.created_at)}</Td>
                  <Td className="max-w-xs truncate">{v.change_description ?? ""}</Td>
                </tr>
              ))}
            </Table>
          </Card>

          {current && (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <Card title={`Logic: ${current.strategy} ${current.version}`}>
                <dl className="space-y-2 text-sm">
                  {Object.entries(current.execution_settings.entry_rules ?? {}).map(([rule, text]) => (
                    <div key={rule}>
                      <dt className="text-ink-2">{rule.replaceAll("_", " ")}</dt>
                      <dd>{text}</dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-3 text-xs text-muted">
                  Indicators are ported from the owner&apos;s Pine Script; entry rules were supplied by the owner. Full documentation,
                  including every implementation choice, is in docs/strategy.md.
                </p>
              </Card>
              <Card title="Indicator settings">
                <Table columns={["Setting", "Value"]}>
                  {Object.entries(current.parameters).map(([k, v]) => (
                    <tr key={k}>
                      <Td>{k}</Td>
                      <Td>{Array.isArray(v) ? v.join(", ") : String(v)}</Td>
                    </tr>
                  ))}
                </Table>
              </Card>
            </div>
          )}

          {current && (
            <Card
              title="Compare versions"
              actions={
                <Field label="Compare with">
                  <Select value={compare ?? ""} onChange={(e) => setCompare(e.target.value || null)}>
                    <option value="">Choose a version</option>
                    {versions.filter((v) => v.id !== current.id).map((v) => (
                      <option key={v.id} value={v.id}>{v.strategy} {v.version}</option>
                    ))}
                  </Select>
                </Field>
              }
            >
              {versions.length < 2 ? (
                <Empty>Only one version exists. Register another to compare.</Empty>
              ) : !other ? (
                <Empty>Choose a version to compare.</Empty>
              ) : (
                <Comparison a={current} b={other} backtests={backtests.data ?? []} />
              )}
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function Comparison({ a, b, backtests }: { a: Version; b: Version; backtests: Backtest[] }) {
  const latest = (v: Version) => backtests.find((t) => t.strategy_version_id === v.id && t.status === "completed") ?? null;
  const [ta, tb] = [latest(a), latest(b)];
  const ma = useApi<Metrics>(ta ? `/backtests/${ta.id}/metrics` : null);
  const mb = useApi<Metrics>(tb ? `/backtests/${tb.id}/metrics` : null);
  const keys = useMemo(() => [...new Set([...Object.keys(a.parameters), ...Object.keys(b.parameters)])], [a, b]);
  const show = (v: unknown) => (Array.isArray(v) ? v.join(", ") : v === undefined ? "n/a" : String(v));

  return (
    <div className="space-y-4">
      <Table columns={["Setting", `${a.strategy} ${a.version}`, `${b.strategy} ${b.version}`]}>
        <tr>
          <Td>code hash</Td>
          <Td className="font-mono text-xs">{a.code_hash.slice(0, 12)}</Td>
          <Td className={`font-mono text-xs ${a.code_hash !== b.code_hash ? "text-warn" : ""}`}>{b.code_hash.slice(0, 12)}</Td>
        </tr>
        {keys.map((k) => {
          const differs = show(a.parameters[k]) !== show(b.parameters[k]);
          return (
            <tr key={k}>
              <Td>{k}</Td>
              <Td>{show(a.parameters[k])}</Td>
              <Td className={differs ? "text-warn" : undefined}>{show(b.parameters[k])}{differs && " (differs)"}</Td>
            </tr>
          );
        })}
      </Table>
      <Table columns={["Latest completed backtest", `${a.version}`, `${b.version}`]}>
        <tr><Td>Range</Td><Td>{ta ? `${ta.start_date} to ${ta.end_date}` : "none"}</Td><Td>{tb ? `${tb.start_date} to ${tb.end_date}` : "none"}</Td></tr>
        <tr><Td>Net points</Td><Td>{signedPoints(ma.data?.net_points)}</Td><Td>{signedPoints(mb.data?.net_points)}</Td></tr>
        <tr><Td>Trades</Td><Td>{ma.data?.total_trades ?? "n/a"}</Td><Td>{mb.data?.total_trades ?? "n/a"}</Td></tr>
        <tr><Td>Win rate</Td><Td>{percent(ma.data?.win_rate)}</Td><Td>{percent(mb.data?.win_rate)}</Td></tr>
        <tr><Td>Max drawdown</Td><Td>{ma.data?.max_drawdown_points?.toFixed(2) ?? "n/a"}</Td><Td>{mb.data?.max_drawdown_points?.toFixed(2) ?? "n/a"}</Td></tr>
      </Table>
      {ta && tb && (ta.start_date !== tb.start_date || ta.end_date !== tb.end_date) && (
        <p className="text-xs text-warn">The backtests cover different date ranges, so their results are not directly comparable.</p>
      )}
    </div>
  );
}
