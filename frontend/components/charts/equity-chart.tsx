"use client";

import { useMemo } from "react";

import { AXIS, EChart, TOOLTIP } from "@/components/charts/echart";
import { CHART } from "@/lib/colors";
import { dateTime, points } from "@/lib/format";
import type { EquityPoint } from "@/types/api";

/** Cumulative points above, drawdown below: two panels on one time axis, each with one y-axis. */
export function EquityChart({ data }: { data: EquityPoint[] }) {
  const option = useMemo(() => {
    const at = (p: EquityPoint, value: number) => [Date.parse(p.ts), value];
    const timeAxis = (gridIndex: number, showLabels: boolean) => ({
      type: "time",
      gridIndex,
      ...AXIS,
      splitLine: { show: false },
      axisLabel: { ...AXIS.axisLabel, show: showLabels, hideOverlap: true, formatter: "{dd} {MMM}" },
    });
    return {
      tooltip: {
        ...TOOLTIP,
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: CHART.muted } },
        formatter: (items: { dataIndex: number }[]) => {
          const p = data[items[0].dataIndex];
          return `${dateTime(p.ts)}<br/>Cumulative: <b>${points(p.cumulative_points)}</b> pts<br/>Drawdown: ${points(p.drawdown_points)} pts`;
        },
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      grid: [
        { left: 64, right: 16, top: 28, height: "50%" },
        { left: 64, right: 16, top: "70%", bottom: 28 },
      ],
      xAxis: [timeAxis(0, false), timeAxis(1, true)],
      yAxis: [
        { type: "value", gridIndex: 0, name: "Cumulative points", nameTextStyle: { color: CHART.muted, align: "left" }, ...AXIS },
        {
          type: "value",
          gridIndex: 1,
          name: "Drawdown",
          nameLocation: "start",
          nameTextStyle: { color: CHART.muted, align: "left", verticalAlign: "bottom" },
          inverse: true,
          splitNumber: 2,
          ...AXIS,
        },
      ],
      series: [
        {
          name: "Cumulative points",
          type: "line",
          data: data.map((p) => at(p, p.cumulative_points)),
          xAxisIndex: 0,
          yAxisIndex: 0,
          // Points change only when a trade exits, so the curve steps instead of sloping.
          step: "end",
          showSymbol: data.length < 60,
          symbolSize: 8,
          lineStyle: { width: 2, color: CHART.gain },
          itemStyle: { color: CHART.gain },
        },
        {
          name: "Drawdown",
          type: "line",
          data: data.map((p) => at(p, p.drawdown_points)),
          xAxisIndex: 1,
          yAxisIndex: 1,
          step: "end",
          showSymbol: false,
          lineStyle: { width: 2, color: CHART.loss },
          areaStyle: { color: CHART.loss, opacity: 0.18 },
        },
      ],
    };
  }, [data]);
  return <EChart option={option} height={340} label="Cumulative points and drawdown after each trade" />;
}
