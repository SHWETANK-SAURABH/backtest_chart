"use client";

import { useMemo } from "react";

import { AXIS, EChart, TOOLTIP } from "@/components/charts/echart";
import { CHART } from "@/lib/colors";
import { points } from "@/lib/format";
import type { PeriodRow } from "@/types/api";

/** Net points per period. Polarity is encoded by the diverging pair: gains blue, losses red. */
export function PeriodBars({ data, label, monthly = false }: { data: PeriodRow[]; label: string; monthly?: boolean }) {
  const option = useMemo(
    () => ({
      tooltip: {
        ...TOOLTIP,
        trigger: "item",
        formatter: (item: { dataIndex: number }) => {
          const row = data[item.dataIndex];
          return `${monthly ? row.trading_date.slice(0, 7) : row.trading_date}<br/>Net: <b>${points(row.net_points)}</b> pts<br/>Trades: ${row.trades} (${row.wins} won, ${row.losses} lost)`;
        },
      },
      grid: { left: 56, right: 16, top: 16, bottom: 28 },
      xAxis: {
        type: "category",
        data: data.map((r) => (monthly ? r.trading_date.slice(0, 7) : r.trading_date.slice(5))),
        ...AXIS,
      },
      yAxis: { type: "value", ...AXIS },
      series: [
        {
          type: "bar",
          name: "Net points",
          barMaxWidth: 28,
          data: data.map((r) => ({
            value: r.net_points,
            itemStyle: {
              color: r.net_points >= 0 ? CHART.gain : CHART.loss,
              borderRadius: r.net_points >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4],
            },
          })),
        },
      ],
    }),
    [data, monthly],
  );
  return <EChart option={option} height={240} label={label} />;
}
