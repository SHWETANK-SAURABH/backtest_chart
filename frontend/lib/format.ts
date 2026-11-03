import type { Backtest } from "@/types/api";

const IST = "Asia/Kolkata";

export function points(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "n/a";
  return value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function signedPoints(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  return `${value > 0 ? "+" : ""}${points(value)}`;
}

export function percent(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined) return "n/a";
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function count(value: number | null | undefined): string {
  return value === null || value === undefined ? "n/a" : value.toLocaleString("en-IN");
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  return new Date(iso).toLocaleString("en-IN", {
    timeZone: IST,
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function time(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: false });
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "n/a";
  const minutes = Math.round(seconds / 60);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function bytes(size: number | null | undefined): string {
  if (!size) return "n/a";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

const MTZ_LABELS = { daily: "daily MTZ", weekly: "weekly MTZ", both: "daily + weekly MTZ" } as const;

/** Timeframe, entry patterns and MTZ choice, for example "15 min · OR, WR · daily MTZ". */
export function strategyOptions(backtest: Backtest): { timeframe: string; patterns: string; mtz: string } {
  const options = backtest.strategy_options;
  const patterns = "entry_patterns" in options ? options.entry_patterns : null;
  return {
    timeframe: backtest.timeframe === "15m" ? "15 min" : "5 min",
    patterns: !patterns || patterns.length === 4 ? "All patterns" : patterns.join(", "),
    mtz: MTZ_LABELS["mtz" in options ? options.mtz : "both"],
  };
}
