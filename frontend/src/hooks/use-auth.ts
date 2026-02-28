import { create } from "zustand";
import type { User } from "@/types/api";
import { loginUser, logoutUser, fetchCurrentUser } from "@/lib/auth";
import { setAccessToken, getAccessToken } from "@/lib/api";

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  initialize: () => Promise<void>;
  clearError: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  error: null,

  login: async (username: string, password: string) => {
    set({ isLoading: true, error: null });
    try {
      const { user } = await loginUser({ username, password });
      set({ user, isAuthenticated: true, isLoading: false, error: null });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Login failed";
      set({ isLoading: false, error: message });
      throw err;
    }
  },

  logout: async () => {
    await logoutUser();
    set({ user: null, isAuthenticated: false, error: null });
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

  clearError: () => set({ error: null }),
}));
