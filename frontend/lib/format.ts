import type { Backtest, BookSetup } from "@/types/api";

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

export const BOOK_SETUP_NAMES: Record<BookSetup, string> = {
  BREAKAWAY: "Breakaway",
  MAGNET: "Magnet (gap fill)",
  CPR_PULLBACK: "CPR pull-back",
  CPR_FADE: "CPR fade",
  TREND_CHANGE: "Trend change",
  PERSON_PLAN: "Person trend plan",
  FLOOR_PIVOT: "Floor pivot",
  CAM_REVERSAL: "H3/L3 reversal",
  CAM_PATTERN: "Camarilla pattern",
  CAM_BREAKOUT: "H4/L4 breakout",
};

const MTZ_LABELS = { daily: "daily MTZ", weekly: "weekly MTZ", both: "daily + weekly MTZ" } as const;

/** A backtest's options as short labels, for example "15 min", "OR, WR", "daily MTZ". */
export function strategyOptions(backtest: Backtest): {
  strategy: string;
  timeframe: string;
  patterns: string;
  mtz: string;
  cpr: string;
  rules: string;
} {
  const options = backtest.strategy_options;
  const patterns = "entry_patterns" in options ? options.entry_patterns : null;
  const thresholds = "cpr_thresholds" in options && options.cpr_thresholds ? options.cpr_thresholds : [0.25, 0.5, 0.75];
  const book = "strategy" in options && options.strategy === "pivot_boss";
  const rules = book
    ? [
        "trend_analysis" in options && options.trend_analysis
          ? "full trend analysis"
          : "weekly_filter" in options && options.weekly_filter
            ? "weekly filter"
            : "no weekly filter",
      ]
    : [
        "day_direction" in options && options.day_direction ? "day direction" : null,
        "adr_trade" in options && options.adr_trade ? "ADR trade" : null,
      ].filter(Boolean);
  if (book && "clear_trend" in options && options.clear_trend) rules.push("clear trend only");
  const setups = "book_setups" in options && options.book_setups ? options.book_setups : [];
  return {
    strategy: book ? "Pivot Boss (book)" : "MTZ reversal",
    timeframe: backtest.timeframe === "15m" ? "15 min" : "5 min",
    patterns: !patterns || patterns.length === 4 ? "All patterns" : patterns.join(", "),
    mtz: book
      ? setups.length === Object.keys(BOOK_SETUP_NAMES).length
        ? "all book setups"
        : setups.map((s) => BOOK_SETUP_NAMES[s]).join(", ")
      : MTZ_LABELS["mtz" in options ? options.mtz : "both"],
    cpr: `CPR ${thresholds.join(" / ")}%`,
    rules: rules.length ? rules.join(", ") : "no direction or ADR rules",
  };
}
