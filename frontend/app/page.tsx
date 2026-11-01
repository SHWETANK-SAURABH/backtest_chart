import { HealthPanel } from "@/components/health-panel";
import { StatTile } from "@/components/stat-tile";
import { getHealth, getInstruments, getOverview } from "@/services/api";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const [health, overview, instruments] = await Promise.allSettled([
    getHealth(),
    getOverview(),
    getInstruments(),
  ]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold">Overview</h1>
        <p className="mt-1 text-sm text-muted">
          Results for the NIFTY 50 spot index are theoretical index points, not rupee profit.
        </p>
      </header>

      <HealthPanel health={health.status === "fulfilled" ? health.value : null} />

      {overview.status === "fulfilled" ? (
        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Platform totals">
          <StatTile label="Backtests" value={overview.value.backtests} />
          <StatTile label="Completed backtests" value={overview.value.completed_backtests} />
          <StatTile label="Strategy versions" value={overview.value.strategy_versions} />
          <StatTile label="Dataset versions" value={overview.value.datasets} />
        </section>
      ) : (
        <p className="rounded border border-line bg-panel p-4 text-sm text-loss">
          Totals are unavailable because the API could not be reached.
        </p>
      )}

      <section className="rounded border border-line bg-panel p-4">
        <h2 className="text-sm font-medium">Instruments</h2>
        {instruments.status === "fulfilled" ? (
          <ul className="mt-2 space-y-1 text-sm">
            {instruments.value.map((instrument) => (
              <li key={instrument.id}>
                {instrument.name} <span className="text-muted">({instrument.exchange})</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-muted">Unavailable.</p>
        )}
      </section>
    </div>
  );
}
