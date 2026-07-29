// =============================================================================
// API Client — thin fetch wrapper with JWT auth and auto-refresh
// =============================================================================

import type { LoginResponse } from "@/types/api";

const BASE_URL = "/api/v1";

// Access tokens stay in memory. The httpOnly refresh cookie restores a session
// after reload without exposing a long-lived credential to JavaScript storage.
let accessToken: string | null = null;
let refreshRequest: Promise<LoginResponse | null> | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function restoreSession(): Promise<LoginResponse | null> {
  if (refreshRequest) return refreshRequest;

  refreshRequest = (async () => {
    try {
      const response = await fetch(`${BASE_URL}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok) return null;

      const data = (await response.json()) as LoginResponse;
      setAccessToken(data.access_token);
      return data;
    } catch {
      return null;
    }
  })().finally(() => {
    refreshRequest = null;
  });

  return refreshRequest;
}

async function tryRefresh(): Promise<boolean> {
  return (await restoreSession()) !== null;
}

async function request<T>(
  path: string,
  options?: RequestInit & { skipAuth?: boolean }
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (!options?.skipAuth && accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }

  // Merge provided headers
  if (options?.headers) {
    const incoming =
      options.headers instanceof Headers
        ? Object.fromEntries(options.headers.entries())
        : Array.isArray(options.headers)
          ? Object.fromEntries(options.headers)
          : options.headers;
    Object.assign(headers, incoming);
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });

  if (res.status === 401 && !options?.skipAuth) {
    const refreshed = await tryRefresh();
    if (!refreshed) {
      // Clear stale token and redirect
      setAccessToken(null);
      window.location.href = "/login";
      throw new Error("Unauthorized");
    }
    // Retry original request with new token
    return request(path, options);
  }

  if (!res.ok) {
    const error = await res
      .json()
      .catch(() => ({ detail: `HTTP ${res.status}` }));
    const apiError = error as { detail?: string };
    throw new Error(apiError.detail ?? `HTTP ${res.status}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),

  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  put: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PUT",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PATCH",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
