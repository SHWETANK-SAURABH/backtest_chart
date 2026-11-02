"use client";

import {
  BrainCircuit,
  ChartCandlestick,
  Database,
  FileText,
  FlaskConical,
  LayoutDashboard,
  ListChecks,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/cn";

const NAV: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/backtests", label: "Backtests", icon: ListChecks },
  { href: "/backtests/new", label: "New backtest", icon: FlaskConical },
  { href: "/data", label: "Historical data", icon: Database },
  { href: "/strategies", label: "Strategies", icon: ChartCandlestick },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/ai-datasets", label: "AI datasets", icon: BrainCircuit },
];

export function Sidebar() {
  const pathname = usePathname();
  // The longest matching link is the active one, so /backtests/new does not also light /backtests.
  const matches = NAV.filter(({ href }) =>
    href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`),
  );
  const current = matches.sort((a, b) => b.href.length - a.href.length)[0]?.href;
  const active = (href: string) => href === current;

  return (
    <aside className="border-b border-line bg-panel px-4 py-3 md:sticky md:top-0 md:h-screen md:w-56 md:shrink-0 md:border-r md:border-b-0 md:py-5">
      <p className="text-sm font-semibold">NIFTY 50 Backtester</p>
      <nav aria-label="Main" className="mt-3 flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            aria-current={active(href) ? "page" : undefined}
            className={cn(
              "flex shrink-0 items-center gap-2 rounded px-2 py-1.5 text-sm text-ink-2 hover:bg-raised hover:text-ink",
              active(href) && "bg-raised text-ink",
            )}
          >
            <Icon aria-hidden className="size-4" />
            {label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
