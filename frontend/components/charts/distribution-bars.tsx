"use client";

import { useMemo } from "react";

import { AXIS, EChart, TOOLTIP } from "@/components/charts/echart";
import { CHART } from "@/lib/colors";

/** Counts per label as horizontal bars, one series in one colour, values labelled at the bar ends. */
export function DistributionBars({ counts, label }: { counts: Record<string, number>; label: string }) {
  const option = useMemo(() => {
    const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    return {
      tooltip: {
        ...TOOLTIP,
        trigger: "item",
        formatter: (i: { name: string; value: number }) => `${i.name}: <b>${i.value.toLocaleString("en-IN")}</b>`,
      },
      grid: { left: 110, right: 56, top: 8, bottom: 8 },
      xAxis: { type: "value", ...AXIS, axisLabel: { show: false }, splitLine: { show: false } },
      yAxis: { type: "category", inverse: true, data: entries.map(([k]) => k), ...AXIS },
      series: [
        {
          type: "bar",
          barMaxWidth: 18,
          data: entries.map(([, v]) => v),
          itemStyle: { color: CHART.series[0], borderRadius: [0, 4, 4, 0] },
          label: {
            show: true,
            position: "right",
            color: CHART.ink2,
            formatter: (p: { value: number }) => p.value.toLocaleString("en-IN"),
          },
        },
      ],
    };
  }, [counts]);
  const rows = Object.keys(counts).length;
  return <EChart option={option} height={Math.max(80, rows * 30 + 16)} label={label} />;
}
