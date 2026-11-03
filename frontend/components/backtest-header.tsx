"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button, PointsNotice, StatusBadge } from "@/components/ui";
import { cn } from "@/lib/cn";
import { shortId, strategyOptions } from "@/lib/format";
import { post } from "@/services/client";
import type { BacktestDetail } from "@/types/api";

export function BacktestHeader({ backtest, onChange }: { backtest: BacktestDetail; onChange: () => void }) {
  const pathname = usePathname();
  const base = `/backtests/${backtest.id}`;
  const tabs = [
    { href: base, label: "Results" },
    { href: `${base}/chart`, label: "Chart" },
    { href: `${base}/trades`, label: "Trades" },
    { href: `/reports?backtest=${backtest.id}`, label: "Reports" },
  ];
  const running = backtest.status === "pending" || backtest.status === "running";
  const options = strategyOptions(backtest);

  return (
    <header className="mb-4 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="flex flex-wrap items-center gap-3 text-xl font-semibold">
            Backtest {shortId(backtest.id)} <StatusBadge status={backtest.status} />
          </h1>
          <p className="mt-1 text-sm text-ink-2">
            {backtest.start_date} to {backtest.end_date} · {options.timeframe} · {options.patterns} · {options.mtz} · {options.cpr} · {options.rules} ·{" "}
            {backtest.execution_method === "signal_close" ? "signal close fills (idealised)" : "next open fills"} · slippage{" "}
            {String(backtest.execution_settings.slippage_points ?? 0)} pts · <PointsNotice />
          </p>
          {backtest.error && <p className="mt-1 text-sm text-critical">{backtest.error}</p>}
        </div>
        {running && (
          <Button variant="secondary" onClick={() => post(`/backtests/${backtest.id}/cancel`, {}).then(onChange)}>
            Cancel
          </Button>
        )}
      </div>
      <nav aria-label="Backtest" className="flex gap-1 overflow-x-auto border-b border-line">
        {tabs.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={pathname === tab.href ? "page" : undefined}
            className={cn(
              "shrink-0 border-b-2 border-transparent px-3 py-2 text-sm text-ink-2 hover:text-ink",
              pathname === tab.href && "border-accent text-ink",
            )}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
