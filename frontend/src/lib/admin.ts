export async function adminJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api/admin/console${path}`, {
    credentials: "include",
    ...init,
    headers,
  });
  if (response.status === 204) {
    return undefined as T;
  }
  const body = (await response.json().catch(() => ({}))) as {
    detail?: string;
    message?: string;
  } & T;
  if (!response.ok) {
    const message =
      typeof body.detail === "string"
        ? body.detail
        : body.message || `Request failed (${response.status})`;
    throw new Error(message);
  }
  return body as T;
}

export function formatEur(value: number): string {
  if (!Number.isFinite(value)) return "€0.00";
  if (value > 0 && value < 0.01) return `€${value.toFixed(6)}`;
  return `€${value.toFixed(2)}`;
}

export function formatSeconds(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0s";
  if (value < 60) return `${value.toFixed(value < 10 ? 2 : 0)}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${seconds}s`;
}

export function formatWhen(value: string | null | undefined): string {
  if (!value) return "Never synced";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
