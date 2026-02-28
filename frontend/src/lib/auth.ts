// =============================================================================
// Auth helpers — token storage and login/logout operations
// =============================================================================

import { api, setAccessToken } from "./api";
import type { LoginRequest, LoginResponse, User } from "@/types/api";

export async function loginUser(
  credentials: LoginRequest
): Promise<{ user: User; token: string }> {
  const response = await api.post<LoginResponse>("/auth/login", credentials);
  setAccessToken(response.access_token);
  return { user: response.user, token: response.access_token };
}

export async function logoutUser(): Promise<void> {
  try {
    await api.post("/auth/logout");
  } catch {
    // Logout may fail if token is already expired — that is acceptable
  }
  setAccessToken(null);
}

export async function refreshAuth(): Promise<{
  user: User;
  token: string;
} | null> {
  try {
    const response = await api.post<LoginResponse>("/auth/refresh");
    setAccessToken(response.access_token);
    return { user: response.user, token: response.access_token };
  } catch {
    setAccessToken(null);
    return null;
  }
}

export async function fetchCurrentUser(): Promise<User | null> {
  try {
    return await api.get<User>("/auth/me");
  } catch {
    return null;
  }
}
