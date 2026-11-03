"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { Button, Card, ErrorBox, Field, Input, Loading, PageHeader, Select } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { get, post } from "@/services/client";
import type { Backtest, MarketDataHealth, Pattern, Strategy, StrategyDetail, StrategyVersion } from "@/types/api";

const PATTERNS: { code: Pattern; name: string }[] = [
  { code: "OR", name: "Outside reversal" },
  { code: "DR", name: "Doji reversal" },
  { code: "ER", name: "Extreme reversal" },
  { code: "WR", name: "Wick reversal" },
];

export default function NewBacktestPage() {
  const router = useRouter();
  const strategies = useApi<Strategy[]>("/strategies");
  const data = useApi<MarketDataHealth>("/market-data/health");
  const [versions, setVersions] = useState<(StrategyVersion & { strategy: string })[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [patterns, setPatterns] = useState<Pattern[]>(PATTERNS.map((p) => p.code));

  useEffect(() => {
    if (!strategies.data) return;
    Promise.all(strategies.data.map((s) => get<StrategyDetail>(`/strategies/${s.id}`)))
      // Newest first, so the default is the latest registered version.
      .then((details) =>
        setVersions(
          details
            .flatMap((d) => d.versions.map((v) => ({ ...v, strategy: d.name })))
            .sort((x, y) => y.created_at.localeCompare(x.created_at)),
        ),
      )
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
        timeframe: form.get("timeframe"),
        strategy_options: {
          entry_patterns: patterns,
          mtz: form.get("mtz"),
          cpr_thresholds: ["cpr_trending", "cpr_possible", "cpr_sideways"].map((name) => Number(form.get(name))),
          day_direction: form.get("day_direction") === "on",
          adr_trade: form.get("adr_trade") === "on",
        },
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
      <PageHeader title="New backtest" description="NIFTY 50 spot, 5- or 15-minute candles. Results are theoretical index points." />
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
              <Field label="Timeframe" hint="15-minute candles are built from the 5-minute data">
                <Select name="timeframe" defaultValue="5m">
                  <option value="5m">5 minutes</option>
                  <option value="15m">15 minutes</option>
                </Select>
              </Field>
              <Field label="Start date" hint={intraday ? `5-minute data covers ${intraday.start_date} to ${intraday.end_date}` : undefined}>
                <Input type="date" name="start_date" required min={intraday?.start_date ?? undefined} max={intraday?.end_date ?? undefined} defaultValue={intraday?.start_date ?? undefined} />
              </Field>
              <Field label="End date" hint={daily ? `Daily data: v${daily.version}` : "No ready daily dataset"}>
                <Input type="date" name="end_date" required min={intraday?.start_date ?? undefined} max={intraday?.end_date ?? undefined} defaultValue={intraday?.end_date ?? undefined} />
              </Field>
            </div>
          </Card>

          <Card title="Entries and exits">
            <div className="grid gap-4 sm:grid-cols-2">
              <fieldset className="text-sm">
                <legend className="mb-1 text-ink-2">Entry patterns</legend>
                <div className="grid grid-cols-2 gap-1">
                  {PATTERNS.map((p) => (
                    <label key={p.code} className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={patterns.includes(p.code)}
                        onChange={(e) =>
                          setPatterns((current) =>
                            e.target.checked ? [...current, p.code] : current.filter((c) => c !== p.code),
                          )
                        }
                      />
                      {p.name} ({p.code})
                    </label>
                  ))}
                </div>
                {patterns.length === 0 && <p className="mt-1 text-xs text-critical">Choose at least one pattern.</p>}
              </fieldset>
              <Field label="Entry zones (MTZ)" hint="Entries come from these zones; the target can be any other MTZ, daily or weekly.">
                <Select name="mtz" defaultValue="both">
                  <option value="both">Daily and weekly MTZ</option>
                  <option value="daily">Daily MTZ only</option>
                  <option value="weekly">Weekly MTZ only</option>
                </Select>
              </Field>
            </div>
            <fieldset className="mt-4 text-sm">
              <legend className="mb-1 text-ink-2">Daily CPR width thresholds (%)</legend>
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Trending below">
                  <Input type="number" name="cpr_trending" min={0.01} max={10} step={0.01} defaultValue={0.25} required />
                </Field>
                <Field label="Possible Trending below">
                  <Input type="number" name="cpr_possible" min={0.01} max={10} step={0.01} defaultValue={0.5} required />
                </Field>
                <Field label="Sideways below" hint="Wider is Sideways Trading">
                  <Input type="number" name="cpr_sideways" min={0.01} max={10} step={0.01} defaultValue={0.75} required />
                </Field>
              </div>
              <p className="mt-1 text-xs text-muted">The script&apos;s values are 0.25, 0.50 and 0.75. Each must be above the one before.</p>
            </fieldset>
            <div className="mt-4 space-y-2 text-sm">
              <label className="flex items-start gap-2">
                <input type="checkbox" name="day_direction" defaultChecked className="mt-1" />
                <span>
                  Day direction
                  <span className="block text-xs text-muted">
                    Longs or shorts only, from the 2-day CPR relationship and opening bias (accepted or rejected). When they give no direction, the latest 15-minute close beyond the CPR sets it.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2">
                <input type="checkbox" name="adr_trade" defaultChecked className="mt-1" />
                <span>
                  ADR trade
                  <span className="block text-xs text-muted">
                    Except on Trending and Possible Trending days: once the day&apos;s range reaches the ADR, one trade against the move, stop at that candle, target the next MTZ. Not blocked by R2/S2, day direction or a Sideways day.
                  </span>
                </span>
              </label>
            </div>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted">
              <li>No new entries once price touches the daily R2 or S2.</li>
              <li>Exit by the daily CPR histogram: Sideways, no trades that day; Sideways Trading, target the next MTZ; Trending and Possible Trending, no target, exit when an opposite-colour candle closes beyond the 5 EMA.</li>
              <li>The stop is always the signal candle&apos;s low (long) or high (short).</li>
            </ul>
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

          <Button type="submit" disabled={submitting || !intraday || !daily || versions.length === 0 || patterns.length === 0}>
            {submitting ? "Starting…" : "Run backtest"}
          </Button>
        </form>
      )}
    </div>
  );
}
