// Browser-side API access. Uses the public API URL; credentials never reach the browser.
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d) => d.msg ?? String(d)).join("; ");
    } catch {
      // Keep the status message.
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export function query(params: Record<string, string | number | undefined | null>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return entries.length ? `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)]))}` : "";
}

export async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  // A degraded health check answers 503 with a useful body.
  if (path === "/health" && response.status === 503) return (await response.json()) as T;
  return parse<T>(response);
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  return parse<T>(
    await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export function downloadUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}
