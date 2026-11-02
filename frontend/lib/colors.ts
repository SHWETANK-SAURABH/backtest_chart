// Chart colours: the reference palette's dark steps. Categorical slots are assigned in fixed order.
export const CHART = {
  surface: "#1a1a19",
  ink: "#f0efec",
  ink2: "#c3c2b7",
  muted: "#898781",
  grid: "#2c2c2a",
  axis: "#383835",
  // Diverging pair for polarity: gains blue, losses red.
  gain: "#3987e5",
  loss: "#e66767",
  series: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
} as const;
