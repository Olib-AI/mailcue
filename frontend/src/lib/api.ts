// =============================================================================
// API Client — thin fetch wrapper with JWT auth and auto-refresh
// =============================================================================

const BASE_URL = "/api/v1";

let accessToken: string | null = localStorage.getItem("access_token");

export function setAccessToken(token: string | null): void {
  accessToken = token;
  if (token) {
    localStorage.setItem("access_token", token);
  } else {
    localStorage.removeItem("access_token");
  }
}

export function getAccessToken(): string | null {
  return accessToken;
}

async function tryRefresh(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) return false;
    const data = (await res.json()) as { access_token: string };
    setAccessToken(data.access_token);
    return true;
  } catch {
    return false;
  }
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

  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
