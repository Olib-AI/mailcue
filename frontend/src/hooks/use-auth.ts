import { create } from "zustand";
import type { User } from "@/types/api";
import {
  loginUser,
  logoutUser,
  fetchCurrentUser,
  verify2fa as verify2faApi,
} from "@/lib/auth";
import { setAccessToken, getAccessToken } from "@/lib/api";

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  requires2fa: boolean;
  tempToken: string | null;
  login: (username: string, password: string) => Promise<void>;
  verify2fa: (code: string) => Promise<void>;
  clear2fa: () => void;
  logout: () => Promise<void>;
  initialize: () => Promise<void>;
  clearError: () => void;
  refreshUser: () => Promise<void>;
}

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  error: null,
  requires2fa: false,
  tempToken: null,

  login: async (username: string, password: string) => {
    set({ isLoading: true, error: null });
    try {
      const result = await loginUser({ username, password });
      if ("requires2fa" in result) {
        set({
          requires2fa: true,
          tempToken: result.tempToken,
          isLoading: false,
          error: null,
        });
      } else {
        set({
          user: result.user,
          isAuthenticated: true,
          isLoading: false,
          error: null,
          requires2fa: false,
          tempToken: null,
        });
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Login failed";
      set({ isLoading: false, error: message });
      throw err;
    }
  },

  verify2fa: async (code: string) => {
    const { tempToken } = get();
    if (!tempToken) {
      set({ error: "No 2FA session active" });
      throw new Error("No 2FA session active");
    }
    set({ isLoading: true, error: null });
    try {
      const result = await verify2faApi({ code, temp_token: tempToken });
      set({
        user: result.user,
        isAuthenticated: true,
        isLoading: false,
        error: null,
        requires2fa: false,
        tempToken: null,
      });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "2FA verification failed";
      set({ isLoading: false, error: message });
      throw err;
    }
  },

  clear2fa: () => set({ requires2fa: false, tempToken: null, error: null }),

  logout: async () => {
    await logoutUser();
    set({
      user: null,
      isAuthenticated: false,
      error: null,
      requires2fa: false,
      tempToken: null,
    });
  },

  initialize: async () => {
    const token = getAccessToken();
    if (!token) {
      set({ isLoading: false });
      return;
    }
    try {
      const user = await fetchCurrentUser();
      if (user) {
        set({ user, isAuthenticated: true, isLoading: false });
      } else {
        setAccessToken(null);
        set({ isLoading: false });
      }
    } catch {
      setAccessToken(null);
      set({ isLoading: false });
    }
  },

  refreshUser: async () => {
    const user = await fetchCurrentUser();
    if (user) {
      set({ user });
    }
  },

  clearError: () => set({ error: null }),
}));
