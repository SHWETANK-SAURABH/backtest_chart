"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  LineSeries,
  LineStyle,
  LineType,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";

import { CHART } from "@/lib/colors";
import type { Decision, Trade } from "@/types/api";

// Lightweight Charts labels its time axis in UTC; shifting by the IST offset makes it read in
// exchange time. The shift is applied only for display.
const IST_OFFSET_SECONDS = 5.5 * 3600;
const toChartTime = (iso: string) => (Date.parse(iso) / 1000 + IST_OFFSET_SECONDS) as UTCTimestamp;

export interface LevelSpec {
  key: string;
  label: string;
  color: string;
  dashed?: boolean;
  value: (d: Decision) => number | null | undefined;
}

// Categorical slots in fixed order; candles use the diverging pair.
export const LEVELS: LevelSpec[] = [
  { key: "daily_tc", label: "Daily TC", color: CHART.series[1], value: (d) => d.market_context.cpr.daily?.tc },
  { key: "daily_bc", label: "Daily BC", color: CHART.series[1], dashed: true, value: (d) => d.market_context.cpr.daily?.bc },
  { key: "weekly_tc", label: "Weekly TC", color: CHART.series[2], value: (d) => d.market_context.cpr.weekly?.tc },
  { key: "weekly_bc", label: "Weekly BC", color: CHART.series[2], dashed: true, value: (d) => d.market_context.cpr.weekly?.bc },
  { key: "cam_h3", label: "Cam H3", color: CHART.series[6], value: (d) => d.market_context.camarilla.h3 as number | null },
  { key: "cam_l3", label: "Cam L3", color: CHART.series[6], dashed: true, value: (d) => d.market_context.camarilla.l3 as number | null },
  { key: "cam_h4", label: "Cam H4", color: CHART.series[3], value: (d) => d.market_context.camarilla.h4 as number | null },
  { key: "cam_l4", label: "Cam L4", color: CHART.series[3], dashed: true, value: (d) => d.market_context.camarilla.l4 as number | null },
  { key: "ema20", label: "EMA 20", color: CHART.series[4], value: (d) => d.market_context.ema20 },
];

export function StrategyChart({
  decisions,
  trades,
  visibleLevels,
  selectedTrade,
  onSelectCandle,
}: {
  decisions: Decision[];
  trades: Trade[];
  visibleLevels: Set<string>;
  selectedTrade: Trade | null;
  onSelectCandle: (index: number) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const levelSeries = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const priceLines = useRef<IPriceLine[]>([]);
  const onSelect = useRef(onSelectCandle);
  onSelect.current = onSelectCandle;

  const indexByTime = useMemo(() => new Map(decisions.map((d, i) => [toChartTime(d.candle_ts) as number, i])), [decisions]);
  const indexByTimeRef = useRef(indexByTime);
  indexByTimeRef.current = indexByTime;

  useEffect(() => {
    if (!container.current) return;
    const instance = createChart(container.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: CHART.surface }, textColor: CHART.muted, fontSize: 11 },
      grid: { vertLines: { color: CHART.grid }, horzLines: { color: CHART.grid } },
      rightPriceScale: { borderColor: CHART.axis },
      timeScale: { borderColor: CHART.axis, timeVisible: true, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    });
    candles.current = instance.addSeries(CandlestickSeries, {
      upColor: CHART.gain,
      downColor: CHART.loss,
      borderVisible: false,
      wickUpColor: CHART.gain,
      wickDownColor: CHART.loss,
    });
    for (const level of LEVELS) {
      levelSeries.current.set(
        level.key,
        instance.addSeries(LineSeries, {
          color: level.color,
          lineWidth: level.key === "ema20" ? 2 : 1,
          lineStyle: level.dashed ? LineStyle.Dashed : LineStyle.Solid,
          // Levels are flat within a session; plain lines respect the gaps between sessions.
          lineType: LineType.Simple,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        }),
      );
    }
    instance.subscribeClick((param) => {
      if (param.time === undefined) return;
      const index = indexByTimeRef.current.get(param.time as number);
      if (index !== undefined) onSelect.current(index);
    });
    chart.current = instance;
    return () => {
      instance.remove();
      chart.current = null;
      levelSeries.current.clear();
    };
  }, []);

  useEffect(() => {
    if (!candles.current) return;
    candles.current.setData(
      decisions.map((d) => ({ time: toChartTime(d.candle_ts), open: d.open, high: d.high, low: d.low, close: d.close })),
    );
    for (const level of LEVELS) {
      levelSeries.current.get(level.key)?.setData(
        decisions.map((d, i) => {
          const value = level.value(d);
          const t = toChartTime(d.candle_ts);
          if (value === null || value === undefined) return { time: t };
          // A point's colour applies to the segment leaving it. Making each session's last point
          // transparent hides the segment into the next session, so daily levels are not joined
          // by a vertical line that would look like a price move.
          const next = decisions[i + 1];
          const sessionEnd = next !== undefined && level.key !== "ema20" && sessionOf(next) !== sessionOf(d);
          return sessionEnd ? { time: t, value, color: "transparent" } : { time: t, value };
        }),
      );
    }

    const markers: SeriesMarker<Time>[] = [];
    for (const d of decisions) {
      if (d.action === "BUY") markers.push({ time: toChartTime(d.candle_ts), position: "belowBar", shape: "arrowUp", color: CHART.gain });
      if (d.action === "SELL") markers.push({ time: toChartTime(d.candle_ts), position: "aboveBar", shape: "arrowDown", color: CHART.loss });
    }
    const first = decisions[0]?.candle_ts;
    const last = decisions.at(-1)?.candle_ts;
    for (const t of trades) {
      if (!first || !last || t.exit_ts < first || t.entry_ts > last) continue;
      // Entries and exits are placed on the candle whose open matches, or the closest earlier one.
      markers.push({ time: snap(toChartTime(t.entry_ts), indexByTime), position: "inBar", shape: "circle", color: CHART.ink, text: `#${t.trade_number}` });
      markers.push({
        // Gap exits fill at a candle's open; other exits are stamped at the candle's close.
        time: snap(toChartTime(t.exit_ts) - (t.exit_reason.endsWith("_GAP") ? 0 : 300), indexByTime),
        position: t.side === "long" ? "aboveBar" : "belowBar",
        shape: "square",
        color: t.net_points >= 0 ? CHART.gain : CHART.loss,
        text: `${t.net_points >= 0 ? "+" : ""}${t.net_points.toFixed(1)}`,
      });
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number));
    const plugin = createSeriesMarkers(candles.current, markers);
    chart.current?.timeScale().fitContent();
    return () => plugin.detach();
  }, [decisions, trades, indexByTime]);

  useEffect(() => {
    for (const level of LEVELS) levelSeries.current.get(level.key)?.applyOptions({ visible: visibleLevels.has(level.key) });
  }, [visibleLevels]);

  useEffect(() => {
    const series = candles.current;
    if (!series) return;
    for (const line of priceLines.current) series.removePriceLine(line);
    priceLines.current = [];
    if (!selectedTrade) return;
    const add = (price: number | null, title: string, color: string) => {
      if (price !== null) priceLines.current.push(series.createPriceLine({ price, title, color, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true }));
    };
    add(selectedTrade.entry_price, `Entry #${selectedTrade.trade_number}`, CHART.ink);
    add(selectedTrade.stop_loss, "Stop", CHART.loss);
    add(selectedTrade.target, "Target", CHART.gain);
    const entry = indexByTime.get(snap(toChartTime(selectedTrade.entry_ts), indexByTime) as number);
    if (entry !== undefined) {
      chart.current?.timeScale().setVisibleLogicalRange({ from: Math.max(0, entry - 30), to: entry + 45 });
    }
  }, [selectedTrade, indexByTime]);

  return <div ref={container} className="h-[460px] w-full" role="img" aria-label="Candlestick chart with strategy levels, signals and trades" />;
}

function sessionOf(decision: Decision): number {
  return Math.floor(toChartTime(decision.candle_ts) / 86400);
}

function snap(time: number, index: Map<number, number>): UTCTimestamp {
  let candidate = time;
  for (let i = 0; i < 400 && !index.has(candidate); i++) candidate -= 300;
  return (index.has(candidate) ? candidate : time) as UTCTimestamp;
}
