import type { Health, Instrument, Overview } from "@/types/api";

// Server components inside Docker reach the API by service name; browsers use the public URL.
const API_BASE_URL =
  process.env.INTERNAL_API_BASE_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://localhost:8000/api/v1";

async function request<T>(path: string, acceptedStatuses: number[] = []): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  if (!response.ok && !acceptedStatuses.includes(response.status)) {
    throw new Error(`API request to ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

// A degraded system answers 503 with a useful body.
export const getHealth = () => request<Health>("/health", [503]);
export const getOverview = () => request<Overview>("/overview");
export const getInstruments = () => request<Instrument[]>("/instruments");
