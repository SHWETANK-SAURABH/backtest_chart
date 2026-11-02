"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { Button, Card, ErrorBox, Field, Input, Loading, PageHeader, Select } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { get, post } from "@/services/client";
import type { Backtest, MarketDataHealth, Strategy, StrategyDetail, StrategyVersion } from "@/types/api";

export default function NewBacktestPage() {
  const router = useRouter();
  const strategies = useApi<Strategy[]>("/strategies");
  const data = useApi<MarketDataHealth>("/market-data/health");
  const [versions, setVersions] = useState<(StrategyVersion & { strategy: string })[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!strategies.data) return;
    Promise.all(strategies.data.map((s) => get<StrategyDetail>(`/strategies/${s.id}`)))
      .then((details) => setVersions(details.flatMap((d) => d.versions.map((v) => ({ ...v, strategy: d.name })))))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [strategies.data]);

  const intraday = data.data?.datasets.find((d) => d.timeframe === "5m" && d.status === "ready");
  const daily = data.data?.datasets.find((d) => d.timeframe === "1d" && d.status === "ready");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const optional = (name: string) => (form.get(name) ? Number(form.get(name)) : null);
    setSubmitting(true);
    setError(null);
    try {
      const job = await post<Backtest>("/backtests", {
        strategy_version_id: form.get("strategy_version_id"),
        start_date: form.get("start_date"),
        end_date: form.get("end_date"),
        execution: { method: form.get("method"), slippage_points: Number(form.get("slippage_points") || 0) },
        risk: { max_trades_per_day: optional("max_trades_per_day"), max_daily_loss_points: optional("max_daily_loss_points") },
        capital: { initial_capital: Number(form.get("initial_capital") || 1000000) },
      });
      router.push(`/backtests/${job.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  }

  const loading = (strategies.loading && !strategies.data) || (data.loading && !data.data);
  return (
    <div className="max-w-3xl">
      <PageHeader title="New backtest" description="NIFTY 50 spot, 5-minute candles. Results are theoretical index points." />
      {loading ? (
        <Loading />
      ) : (
        <form onSubmit={submit} className="space-y-4">
          {error && <ErrorBox message={error} />}
          {!intraday && <ErrorBox message="No ready 5-minute dataset. Download market data first." />}
          {versions.length === 0 && <ErrorBox message="No strategy version registered yet. Register one with scripts/register_strategy.py." />}

          <Card title="Strategy and data">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Strategy version">
                <Select name="strategy_version_id" required>
                  {versions.map((v) => (
                    <option key={v.id} value={v.id}>{v.strategy} {v.version}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Instrument and timeframe">
                <Input value="NIFTY 50 (NSE), 5 minutes" disabled readOnly />
              </Field>
              <Field label="Start date" hint={intraday ? `5-minute data covers ${intraday.start_date} to ${intraday.end_date}` : undefined}>
                <Input type="date" name="start_date" required min={intraday?.start_date ?? undefined} max={intraday?.end_date ?? undefined} defaultValue={intraday?.start_date ?? undefined} />
              </Field>
              <Field label="End date" hint={daily ? `Daily data: v${daily.version}` : "No ready daily dataset"}>
                <Input type="date" name="end_date" required min={intraday?.start_date ?? undefined} max={intraday?.end_date ?? undefined} defaultValue={intraday?.end_date ?? undefined} />
              </Field>
            </div>
          </Card>

          <Card title="Execution">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Entry fill" hint="Signal close is idealised: that price is only known as the candle closes.">
                <Select name="method" defaultValue="next_open">
                  <option value="next_open">Next candle open</option>
                  <option value="signal_close">Signal candle close (idealised)</option>
                </Select>
              </Field>
              <Field label="Slippage (points)" hint="Applied to entries, stop exits and square-offs.">
                <Input type="number" name="slippage_points" min={0} max={100} step={0.05} defaultValue={0} />
              </Field>
            </div>
          </Card>

          <Card title="Risk and capital">
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Max trades per day" hint="Blank for no limit">
                <Input type="number" name="max_trades_per_day" min={1} step={1} />
              </Field>
              <Field label="Max daily loss (points)" hint="Blank for no limit">
                <Input type="number" name="max_daily_loss_points" min={0.05} step={0.05} />
              </Field>
              <Field label="Initial capital (INR)" hint="Recorded only; results stay in points">
                <Input type="number" name="initial_capital" min={1} step={1} defaultValue={1000000} />
              </Field>
            </div>
          </Card>

          <Button type="submit" disabled={submitting || !intraday || !daily || versions.length === 0}>
            {submitting ? "Starting…" : "Run backtest"}
          </Button>
        </form>
      )}
    </div>
  );
}
