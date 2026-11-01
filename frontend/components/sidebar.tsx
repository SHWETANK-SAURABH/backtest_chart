import Link from "next/link";

// Other pages are added to this list as the phases that power them are completed.
const NAV_ITEMS = [{ href: "/", label: "Overview" }];

export function Sidebar() {
  return (
    <aside className="border-b border-line bg-panel p-4 md:min-h-screen md:w-56 md:border-b-0 md:border-r">
      <p className="text-sm font-semibold">NIFTY 50 Backtester</p>
      <nav className="mt-3 flex gap-3 md:flex-col md:gap-1" aria-label="Main">
        {NAV_ITEMS.map((item) => (
          <Link key={item.href} href={item.href} className="text-sm text-muted hover:text-ink">
            {item.label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
