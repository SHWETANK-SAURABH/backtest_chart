import { CircleAlert, CircleCheck } from "lucide-react";

import type { ComponentHealth, Health } from "@/types/api";

function Row({ name, component }: { name: string; component: ComponentHealth | null }) {
  const ok = component?.status === "ok";
  const Icon = ok ? CircleCheck : CircleAlert;
  return (
    <li className="flex items-center gap-2 text-sm">
      <Icon aria-hidden className={ok ? "size-4 text-good" : "size-4 text-critical"} />
      <span>{name}</span>
      <span className="text-ink-2">{component ? (ok ? "Connected" : "Unavailable") : "Checking"}</span>
    </li>
  );
}

export function HealthPanel({ health, unreachable = false }: { health: Health | null; unreachable?: boolean }) {
  const api: ComponentHealth | null = unreachable ? { status: "unavailable", detail: null } : health ? { status: "ok", detail: null } : null;
  return (
    <section className="rounded border border-line bg-panel p-4">
      <h2 className="text-sm font-medium">System status</h2>
      <ul className="mt-2 flex flex-wrap gap-x-6 gap-y-1">
        <Row name="API" component={api} />
        <Row name="Database" component={unreachable ? api : (health?.database ?? null)} />
        <Row name="Redis" component={unreachable ? api : (health?.redis ?? null)} />
      </ul>
    </section>
  );
}
