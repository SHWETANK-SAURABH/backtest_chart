import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Sidebar } from "@/components/sidebar";

import "./globals.css";

export const metadata: Metadata = {
  title: "NIFTY 50 Backtester",
  description: "NIFTY 50 intraday backtesting and strategy analytics",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col antialiased md:flex-row">
        <Sidebar />
        <main className="min-w-0 flex-1 p-4 md:p-6">{children}</main>
      </body>
    </html>
  );
}
