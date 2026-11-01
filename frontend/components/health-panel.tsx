import { CircleAlert, CircleCheck } from "lucide-react";

import type { ComponentHealth, Health } from "@/types/api";

function Row({ name, component }: { name: string; component: ComponentHealth | null }) {
  const ok = component?.status === "ok";
  const Icon = ok ? CircleCheck : CircleAlert;
  return (
    <li className="flex items-center gap-2 text-sm">
      <Icon aria-hidden className={ok ? "size-4 text-gain" : "size-4 text-loss"} />
      <span>{name}</span>
      <span className="text-muted">{ok ? "Connected" : "Unavailable"}</span>
    </li>
  );
}

export function HealthPanel({ health }: { health: Health | null }) {
  return (
    <section className="rounded border border-line bg-panel p-4">
      <h2 className="text-sm font-medium">System status</h2>
      <ul className="mt-2 flex flex-wrap gap-x-6 gap-y-1">
        <Row name="API" component={health ? { status: "ok", detail: null } : null} />
        <Row name="Database" component={health?.database ?? null} />
        <Row name="Redis" component={health?.redis ?? null} />
      </ul>
    </section>
  );
}
