// =============================================================================
// Auth helpers — token storage and login/logout operations
// =============================================================================

import { api, setAccessToken } from "./api";
import type {
  ChangePasswordRequest,
  LoginRequest,
  LoginResponse,
  LoginStepResponse,
  TOTPSetupResponse,
  TwoFactorVerifyRequest,
  User,
} from "@/types/api";
import { isLoginStepResponse } from "@/types/api";

export async function loginUser(
  credentials: LoginRequest
): Promise<
  { user: User; token: string } | { requires2fa: true; tempToken: string }
> {
  const response = await api.post<LoginResponse | LoginStepResponse>(
    "/auth/login",
    credentials
  );

  if (isLoginStepResponse(response)) {
    return { requires2fa: true, tempToken: response.temp_token };
  }

  setAccessToken(response.access_token);
  return { user: response.user, token: response.access_token };
}

export async function verify2fa(
  request: TwoFactorVerifyRequest
): Promise<{ user: User; token: string }> {
  const response = await api.post<LoginResponse>("/auth/login/2fa", request);
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

export async function changePassword(
  request: ChangePasswordRequest
): Promise<void> {
  await api.put("/auth/password", request);
}

export async function setupTotp(): Promise<TOTPSetupResponse> {
  return api.post<TOTPSetupResponse>("/auth/totp/setup");
}

export async function confirmTotp(code: string): Promise<void> {
  await api.post("/auth/totp/confirm", { code });
}

export async function disableTotp(
  password: string,
  code: string
): Promise<void> {
  await api.post("/auth/totp/disable", { password, code });
}
