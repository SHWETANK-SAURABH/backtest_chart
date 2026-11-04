"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { Button, Card, ErrorBox, Field, Input, Loading, PageHeader, Select } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { get, post } from "@/services/client";
import { BOOK_SETUP_NAMES, ZONE_TYPE_NAMES } from "@/lib/format";
import type {
  Backtest,
  BookSetup,
  MarketDataHealth,
  Pattern,
  Strategy,
  StrategyDetail,
  StrategyKind,
  StrategyVersion,
  ZoneType,
} from "@/types/api";

const PATTERNS: { code: Pattern; name: string }[] = [
  { code: "OR", name: "Outside reversal" },
  { code: "DR", name: "Doji reversal" },
  { code: "ER", name: "Extreme reversal" },
  { code: "WR", name: "Wick reversal" },
];

const BOOK_SETUPS: { code: BookSetup; rule: string }[] = [
  { code: "BREAKAWAY", rule: "Narrow CPR; open gaps beyond the prior high/low and R1/S1, not past R2/S2; first candle tests the pivot and holds. Stop: day's extreme. Target R3/S3 with a 1.5 ATR trail." },
  { code: "MAGNET", rule: "The script's magnet gap; a reversal candle toward the CPR in the first hour. Stop: day's extreme. Target: the CPR." },
  { code: "TREND_CHANGE", rule: "After a strong day (close at a 5-day high, range at least the ADR): a wick reversal at the CPR by 11:15. Stop: the wick candle. Target R1 (S1 after a strong down day)." },
  { code: "CPR_PULLBACK", rule: "Bias confirmed by the open and a Higher/Lower Value relationship; a reversal candle at the CPR before 11:15. Stop: far side of the CPR. Target R1/S1." },
  { code: "CPR_FADE", rule: "The open rejects the bias: a reversal candle at the CPR the other way. Stop: that candle. Target S1/R1." },
  { code: "PERSON_PLAN", rule: "John Person's filter: S1/R1 uptrend, a reversal pattern at S1 or the CPR, target R1; downtrend, at R1 or the CPR, target S1. Stop beyond the level." },
  { code: "FLOOR_PIVOT", rule: "Prior two closes on the same side of their CPRs: a reversal candle at the CPR or S1 (R1 in a downtrend). Stop beyond the level. Target R1/S1." },
  { code: "CAM_REVERSAL", rule: "Wick through L3/H3 closing back inside, then a confirming candle. Stop L4/H4. Target H3/L3." },
  { code: "CAM_PATTERN", rule: "One of the 4 reversal patterns at a Camarilla level. Wide CPR: L3 long / H3 short, stop L4/H4, target the opposite level. Narrow CPR: L3 or L4 long / H3 or H4 short, stop one level out, 5 EMA trailing exit." },
  { code: "CAM_BREAKOUT", rule: "After a failed test of H4/L4, the first close beyond it and beyond the test's high/low. Stop H3/L3. Target H5/L5." },
];

const ZONE_TYPES: { code: ZoneType; rule: string }[] = [
  { code: "MTF", rule: "A day level (PP, TC, BC, R1, R2, S1, S2, H3-H5, L3-L5) with levels of other timeframes nearby; score 1 + each timeframe that has one." },
  { code: "GPZ", rule: "CPR TC/BC/PP near Camarilla H3 (bull) or L3 (bear), on the day, week or month." },
  { code: "DPZ", rule: "R2 near H4 (bull) or S2 near L4 (bear)." },
  { code: "MTF_STAR", rule: "The day's R1 near the week's or top timeframe's PP/TC (bull); S1 near PP/BC (bear)." },
  { code: "PP_CC", rule: "A pivot near its Camarilla centre (always bull in the script)." },
];

export default function NewBacktestPage() {
  const router = useRouter();
  const strategies = useApi<Strategy[]>("/strategies");
  const data = useApi<MarketDataHealth>("/market-data/health");
  const [versions, setVersions] = useState<(StrategyVersion & { strategy: string })[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [patterns, setPatterns] = useState<Pattern[]>(PATTERNS.map((p) => p.code));
  const [kind, setKind] = useState<StrategyKind>("mtz_reversal");
  const [setups, setSetups] = useState<BookSetup[]>(BOOK_SETUPS.map((s) => s.code));
  const book = kind === "pivot_boss";
  const hz = kind === "hot_zone";
  const [zoneTypes, setZoneTypes] = useState<ZoneType[]>(["MTF", "GPZ"]);

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
          strategy: kind,
          book_setups: setups,
          weekly_filter: form.get("weekly_filter") === "on",
          trend_analysis: form.get("trend_analysis") === "on",
          clear_trend: form.get("clear_trend") === "on",
          hz_types: zoneTypes,
          hz_min_score: Number(form.get("hz_min_score") ?? 2),
          hz_panel_gate: form.get("hz_panel_gate") === "on",
          entry_patterns: patterns,
          mtz: form.get("mtz") ?? "both",
          cpr_thresholds: ["cpr_trending", "cpr_possible", "cpr_sideways"].map((name) => Number(form.get(name))),
          // Only the MTZ reversal reads these; the defaults are sent for the other strategies.
          day_direction: book || hz || form.get("day_direction") === "on",
          adr_trade: book || hz || form.get("adr_trade") === "on",
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
            <Field label="Strategy" hint="The book strategy follows prompt/mainbook.txt where it differs from book.txt.">
              <Select value={kind} onChange={(e) => setKind(e.target.value as StrategyKind)}>
                <option value="mtz_reversal">MTZ reversal (current)</option>
                <option value="pivot_boss">Pivot Boss (book)</option>
                <option value="hot_zone">Hot zone scalp (strategy4)</option>
              </Select>
            </Field>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <fieldset className="text-sm">
                <legend className="mb-1 text-ink-2">{book || hz ? "Reversal candle triggers" : "Entry patterns"}</legend>
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
              {book ? (
                <div className="space-y-2 text-sm">
                  <label className="flex items-start gap-2">
                    <input type="checkbox" name="trend_analysis" className="mt-1" />
                    <span>
                      Full trend analysis
                      <span className="block text-xs text-muted">
                        Every setup must agree with: the 7 two-day CPR relationships (Higher longs; Overlapping Higher longs, shorts only on 2+ patterns; Unchanged by the open; Outside both; Inside the first 15-minute break), flipped when the open rejects them; the S1/R1 floor-pivot trend; and the weekly trend. Replaces the weekly filter.
                      </span>
                    </span>
                  </label>
                  <label className="flex items-start gap-2">
                    <input type="checkbox" name="clear_trend" className="mt-1" />
                    <span>
                      Clear trend only
                      <span className="block text-xs text-muted">
                        Trend setups (breakaway, CPR pull-back, Person plan, floor pivot, H4/L4 breakout) trade only when the S1/R1 trend, the day&apos;s relationship side and the weekly trend all agree. The market trends only about 30% of the time.
                      </span>
                    </span>
                  </label>
                  <label className="flex items-start gap-2">
                    <input type="checkbox" name="weekly_filter" defaultChecked className="mt-1" />
                    <span>
                      Weekly trend filter
                      <span className="block text-xs text-muted">
                        Longs only when last week closed at or above its CPR, shorts only at or below it. Ignored with full trend analysis.
                      </span>
                    </span>
                  </label>
                </div>
              ) : hz ? (
                <div className="space-y-2 text-sm">
                  <Field label="MTF confluence minimum score" hint="1 for the day plus 1 per other timeframe with a level nearby">
                    <Select name="hz_min_score" defaultValue="2">
                      <option value="2">2</option>
                      <option value="3">3</option>
                      <option value="4">4</option>
                    </Select>
                  </Field>
                  <label className="flex items-start gap-2">
                    <input type="checkbox" name="hz_panel_gate" className="mt-1" />
                    <span>
                      Trade direction panel gate
                      <span className="block text-xs text-muted">
                        Enter only when the panel allows the side from structure, a gap beyond R1/S1 or an open beyond the prior high/low (not from the zone itself).
                      </span>
                    </span>
                  </label>
                </div>
              ) : (
                <Field label="Entry zones (MTZ)" hint="Entries come from these zones; the target can be any other MTZ, daily or weekly.">
                  <Select name="mtz" defaultValue="both">
                    <option value="both">Daily and weekly MTZ</option>
                    <option value="daily">Daily MTZ only</option>
                    <option value="weekly">Weekly MTZ only</option>
                  </Select>
                </Field>
              )}
            </div>
            {hz && (
              <fieldset className="mt-4 text-sm">
                <legend className="mb-1 text-ink-2">Hot zone types</legend>
                <div className="space-y-2">
                  {ZONE_TYPES.map((z) => (
                    <label key={z.code} className="flex items-start gap-2">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={zoneTypes.includes(z.code)}
                        onChange={(e) =>
                          setZoneTypes((current) =>
                            e.target.checked ? [...current, z.code] : current.filter((c) => c !== z.code),
                          )
                        }
                      />
                      <span>
                        {ZONE_TYPE_NAMES[z.code]}
                        <span className="block text-xs text-muted">{z.rule}</span>
                      </span>
                    </label>
                  ))}
                </div>
                {zoneTypes.length === 0 && <p className="mt-1 text-xs text-critical">Choose at least one zone type.</p>}
              </fieldset>
            )}
            {book && (
              <fieldset className="mt-4 text-sm">
                <legend className="mb-1 text-ink-2">Book setups</legend>
                <div className="space-y-2">
                  {BOOK_SETUPS.map((s) => (
                    <label key={s.code} className="flex items-start gap-2">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={setups.includes(s.code)}
                        onChange={(e) =>
                          setSetups((current) =>
                            e.target.checked ? [...current, s.code] : current.filter((c) => c !== s.code),
                          )
                        }
                      />
                      <span>
                        {BOOK_SETUP_NAMES[s.code]}
                        <span className="block text-xs text-muted">{s.rule}</span>
                      </span>
                    </label>
                  ))}
                </div>
                {setups.length === 0 && <p className="mt-1 text-xs text-critical">Choose at least one setup.</p>}
              </fieldset>
            )}
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
            <div className={book || hz ? "hidden" : "mt-4 space-y-2 text-sm"}>
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
            {hz ? (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted">
                <li>As strategy4.txt: the zone nearest the close sets the side (bull zone long, bear zone short), however far away it is.</li>
                <li>Entry on a chosen reversal candle in that direction. Stop: the signal candle. Target: the next daily CPR or Camarilla (H3-H6, L3-L6) level beyond the close.</li>
                <li>Zone tolerance is the strategy&apos;s 0.25%. Open trades exit at the session&apos;s close.</li>
              </ul>
            ) : book ? (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted">
                <li>Daily bias: yesterday&apos;s close against its own CPR. Narrow days are Trending and Possible Trending by the thresholds above.</li>
                <li>Setups are checked in the order listed; the first valid one enters. A setup is skipped when price is already beyond its stop or target.</li>
                <li>Open trades exit at the session&apos;s close. The book suggests at most 2 trades a day: set it under Risk if wanted.</li>
              </ul>
            ) : (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted">
              <li>No new entries once price touches the daily R2 or S2.</li>
              <li>Exit by the daily CPR histogram: Sideways, no trades that day; Sideways Trading, target the next MTZ; Trending and Possible Trending, no target, exit when an opposite-colour candle closes beyond the 5 EMA.</li>
              <li>The stop is always the signal candle&apos;s low (long) or high (short).</li>
            </ul>
            )}
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

          <Button type="submit" disabled={submitting || !intraday || !daily || versions.length === 0 || patterns.length === 0 || (book && setups.length === 0) || (hz && zoneTypes.length === 0)}>
            {submitting ? "Starting…" : "Run backtest"}
          </Button>
        </form>
      )}
    </div>
  );
}
