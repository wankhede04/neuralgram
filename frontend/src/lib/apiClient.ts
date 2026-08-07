const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

function getStoredApiKey(): string | null {
  const raw = localStorage.getItem("neuralgram_session");
  if (!raw) return null;
  try {
    return (JSON.parse(raw) as { apiKey: string }).apiKey;
  } catch {
    return null;
  }
}

async function request<T>(
  method: "GET" | "POST",
  path: string,
  options: { params?: Record<string, string>; body?: unknown } = {}
): Promise<T> {
  const url = new URL(path, BASE_URL);
  if (options.params) {
    for (const [key, value] of Object.entries(options.params)) {
      url.searchParams.set(key, value);
    }
  }

  const apiKey = getStoredApiKey();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) headers["x-api-key"] = apiKey;

  const response = await fetch(url.toString(), {
    method,
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (response.status === 401) {
    onUnauthorized?.();
    throw new ApiError(401, "Session expired or invalid. Please sign in again.");
  }

  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, text || `Request failed with status ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export const apiClient = {
  get: <T>(path: string, params?: Record<string, string>) =>
    request<T>("GET", path, { params }),
  post: <T>(path: string, body: unknown) => request<T>("POST", path, { body }),
};
