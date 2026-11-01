export function StatTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-line bg-panel p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value.toLocaleString("en-IN")}</p>
    </div>
  );
}
