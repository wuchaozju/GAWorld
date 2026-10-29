/**
 * Authentication store for session management.
 *
 * Manages user authentication state, tokens, and proactive token refresh.
 * Tokens refresh automatically before expiry when WebSocket is connected
 * to prevent mid-experiment logouts.
 *
 * Exports: useAuthStore (Zustand store hook)
 */

import { create } from "zustand";

type AuthState = {
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  user: Record<string, unknown> | null;
  hasRestored: boolean;
  // Proactive refresh state
  refreshTimerId: ReturnType<typeof setTimeout> | null;
  webSocketConnected: boolean;
  setSession: (payload: {
    accessToken: string;
    refreshToken: string;
    user: Record<string, unknown>;
  }) => void;
  clearSession: () => void;
  restoreSession: () => void;
  updateTokens: (accessToken: string, refreshToken: string) => void;
  // Proactive refresh methods
  setWebSocketConnected: (connected: boolean) => void;
  setupProactiveRefresh: () => void;
  clearProactiveRefresh: () => void;
};

/**
 * Decode JWT token to extract expiry timestamp.
 * Returns expiry time in milliseconds, or null if decoding fails.
 */
function getTokenExpiry(token: string): number | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const payload = JSON.parse(atob(parts[1]));
    return payload.exp ? payload.exp * 1000 : null;
  } catch {
    return null;
  }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  refreshToken: null,
  isAuthenticated: false,
  user: null,
  hasRestored: false,
  refreshTimerId: null,
  webSocketConnected: false,

  setSession: ({ accessToken, refreshToken, user }) => {
    localStorage.setItem("fos.access", accessToken);
    localStorage.setItem("fos.refresh", refreshToken);
    localStorage.setItem("fos.user", JSON.stringify(user));
    set({
      accessToken,
      refreshToken,
      user,
      isAuthenticated: true,
      hasRestored: true,
    });
    // Setup proactive refresh if WebSocket is connected
    const state = get();
    if (state.webSocketConnected) {
      state.setupProactiveRefresh();
    }
  },

  clearSession: () => {
    // Clear proactive refresh timer
    get().clearProactiveRefresh();
    localStorage.removeItem("fos.access");
    localStorage.removeItem("fos.refresh");
    localStorage.removeItem("fos.user");
    set({ accessToken: null, refreshToken: null, user: null, isAuthenticated: false, hasRestored: true });
  },

  updateTokens: (accessToken, refreshToken) => {
    const userRaw = localStorage.getItem("fos.user");
    if (accessToken) {
      localStorage.setItem("fos.access", accessToken);
    }
    if (refreshToken) {
      localStorage.setItem("fos.refresh", refreshToken);
    }
    set((state) => ({
      accessToken,
      refreshToken,
      user: state.user ?? (userRaw ? JSON.parse(userRaw) : null),
      isAuthenticated: true,
      hasRestored: true,
    }));
    // Setup proactive refresh if WebSocket is connected
    const currentState = get();
    if (currentState.webSocketConnected) {
      currentState.setupProactiveRefresh();
    }
  },

  restoreSession: () => {
    const access = localStorage.getItem("fos.access");
    const refresh = localStorage.getItem("fos.refresh");
    const userRaw = localStorage.getItem("fos.user");
    if (!access || !refresh || !userRaw) {
      set({ accessToken: null, refreshToken: null, user: null, isAuthenticated: false, hasRestored: true });
      return;
    }
    try {
      const user = JSON.parse(userRaw) as Record<string, unknown>;
      set({ accessToken: access, refreshToken: refresh, user, isAuthenticated: true, hasRestored: true });
      // Setup proactive refresh if WebSocket is already connected
      const state = get();
      if (state.webSocketConnected) {
        state.setupProactiveRefresh();
      }
    } catch (error) {
      console.error("Failed to parse stored user", error);
      localStorage.removeItem("fos.access");
      localStorage.removeItem("fos.refresh");
      localStorage.removeItem("fos.user");
      set({ accessToken: null, refreshToken: null, user: null, isAuthenticated: false, hasRestored: true });
    }
  },

  setWebSocketConnected: (connected: boolean) => {
    set({ webSocketConnected: connected });
    if (connected) {
      get().setupProactiveRefresh();
    } else {
      get().clearProactiveRefresh();
    }
  },

  setupProactiveRefresh: () => {
    const state = get();

    // Clear existing timer
    if (state.refreshTimerId) {
      clearTimeout(state.refreshTimerId);
      set({ refreshTimerId: null });
    }

    // Only setup if authenticated and WebSocket connected
    if (!state.isAuthenticated || !state.webSocketConnected || !state.accessToken) {
      return;
    }

    const expiry = getTokenExpiry(state.accessToken);
    if (!expiry) {
      console.warn("Could not determine token expiry - skipping proactive refresh");
      return;
    }

    const now = Date.now();
    const fiveMinutes = 5 * 60 * 1000;
    const timeUntilRefresh = expiry - now - fiveMinutes;

    // Edge case: token already expired
    if (expiry <= now) {
      console.warn("Token already expired - clearing session");
      state.clearSession();
      return;
    }

    // Edge case: token expires in less than 5 minutes - refresh immediately via reactive mechanism
    if (timeUntilRefresh <= 0) {
      import("../services/authRuntime").then(({ pingAuthenticatedSession }) => {
        pingAuthenticatedSession(state.accessToken!).catch(() => {
          // 401 will trigger reactive refresh in client.ts
        });
      }).catch(() => {
        // 401 will trigger reactive refresh in client.ts
      });
      return;
    }

    // Schedule refresh for 5 minutes before expiry
    const timerId = setTimeout(async () => {
      const currentState = get();

      // Re-check conditions at execution time
      if (!currentState.webSocketConnected) {
        return;
      }

      if (!currentState.refreshToken) {
        console.warn("No refresh token available - cannot refresh");
        return;
      }

      try {
        const { refreshSessionTokens } = await import("../services/authRuntime");
        const data = await refreshSessionTokens(currentState.refreshToken);
        currentState.updateTokens(data.access_token, data.refresh_token);
      } catch (error) {
        console.error("Proactive token refresh failed:", error);
        // Don't clear session - reactive handler in client.ts will deal with 401
      }
    }, timeUntilRefresh);

    set({ refreshTimerId: timerId });
  },

  clearProactiveRefresh: () => {
    const state = get();
    if (state.refreshTimerId) {
      clearTimeout(state.refreshTimerId);
      set({ refreshTimerId: null });
    }
  },
}));
