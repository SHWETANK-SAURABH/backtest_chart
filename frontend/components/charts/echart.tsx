"use client";

import * as echarts from "echarts";
import { useEffect, useRef } from "react";

import { CHART } from "@/lib/colors";

/** Shared axis and tooltip styling: recessive grid and axes, text in ink tokens. */
export const AXIS = {
  axisLine: { lineStyle: { color: CHART.axis } },
  axisTick: { show: false },
  axisLabel: { color: CHART.muted, fontSize: 11 },
  splitLine: { lineStyle: { color: CHART.grid } },
};

export const TOOLTIP = {
  backgroundColor: "#232321",
  borderColor: CHART.axis,
  textStyle: { color: CHART.ink, fontSize: 12 },
};

export function EChart({ option, height = 280, label }: { option: echarts.EChartsCoreOption; height?: number; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "svg" });
    const observer = new ResizeObserver(() => chart.current?.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption({ backgroundColor: "transparent", textStyle: { fontFamily: "system-ui, sans-serif" }, ...option }, true);
  }, [option]);

  return <div ref={ref} role="img" aria-label={label} style={{ height }} className="w-full" />;
}
