/**
 * Unit tests for proactive token refresh (BUG-CTX-03).
 *
 * Verifies that tokens refresh automatically before expiry when WebSocket is connected.
 */

import { describe, it, expect, beforeEach, afterEach, vi, beforeAll, afterAll } from "vitest";

const authRuntimeMocks = vi.hoisted(() => ({
  refreshSessionTokens: vi.fn(),
  pingAuthenticatedSession: vi.fn(),
}));

// Mock the client module BEFORE importing auth store
vi.mock("../services/client", () => ({
  API_BASE_URL: "http://localhost:8000/api",
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  }
}));

vi.mock("../services/authRuntime", () => ({
  refreshSessionTokens: authRuntimeMocks.refreshSessionTokens,
  pingAuthenticatedSession: authRuntimeMocks.pingAuthenticatedSession,
}));

import { useAuthStore } from "../store/auth";

// Helper to create a mock JWT token with specific expiry
function createMockToken(expSeconds: number): string {
  const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = btoa(JSON.stringify({ exp: expSeconds, sub: "test-user" }));
  const signature = "mock-signature";
  return `${header}.${payload}.${signature}`;
}

describe("Proactive Token Refresh", () => {
  beforeAll(() => {
    vi.useFakeTimers();
  });

  afterAll(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    // Reset store state
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      user: null,
      hasRestored: true,
      refreshTimerId: null,
      webSocketConnected: false,
    });
    vi.clearAllTimers();
    authRuntimeMocks.refreshSessionTokens.mockReset();
    authRuntimeMocks.pingAuthenticatedSession.mockReset();
    localStorage.clear();
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  describe("setWebSocketConnected", () => {
    it("should not setup refresh timer when WebSocket is disconnected", () => {
      // Create a mock token that expires in 20 minutes
      const futureExpiry = Math.floor(Date.now() / 1000) + 20 * 60;
      const mockToken = createMockToken(futureExpiry);

      useAuthStore.getState().setSession({
        accessToken: mockToken,
        refreshToken: "refresh-token",
        user: { id: 1 },
      });

      expect(useAuthStore.getState().refreshTimerId).toBeNull();
    });

    it("should setup refresh timer when WebSocket connects", () => {
      // Create a mock token that expires in 20 minutes
      const futureExpiry = Math.floor(Date.now() / 1000) + 20 * 60;
      const mockToken = createMockToken(futureExpiry);

      useAuthStore.getState().setSession({
        accessToken: mockToken,
        refreshToken: "refresh-token",
        user: { id: 1 },
      });

      useAuthStore.getState().setWebSocketConnected(true);

      expect(useAuthStore.getState().refreshTimerId).not.toBeNull();
    });

    it("should clear timer when WebSocket disconnects", () => {
      const futureExpiry = Math.floor(Date.now() / 1000) + 20 * 60;
      const mockToken = createMockToken(futureExpiry);

      useAuthStore.getState().setSession({
        accessToken: mockToken,
        refreshToken: "refresh-token",
        user: { id: 1 },
      });

      useAuthStore.getState().setWebSocketConnected(true);
      expect(useAuthStore.getState().refreshTimerId).not.toBeNull();

      useAuthStore.getState().setWebSocketConnected(false);
      expect(useAuthStore.getState().refreshTimerId).toBeNull();
    });
  });

  describe("clearSession", () => {
    it("should clear timer when session is cleared", () => {
      const futureExpiry = Math.floor(Date.now() / 1000) + 20 * 60;
      const mockToken = createMockToken(futureExpiry);

      useAuthStore.getState().setSession({
        accessToken: mockToken,
        refreshToken: "refresh-token",
        user: { id: 1 },
      });

      useAuthStore.getState().setWebSocketConnected(true);
      expect(useAuthStore.getState().refreshTimerId).not.toBeNull();

      useAuthStore.getState().clearSession();
      expect(useAuthStore.getState().refreshTimerId).toBeNull();
      expect(useAuthStore.getState().isAuthenticated).toBe(false);
    });
  });

  describe("setupProactiveRefresh", () => {
    it("should not setup timer when not authenticated", () => {
      useAuthStore.getState().setWebSocketConnected(true);

      expect(useAuthStore.getState().refreshTimerId).toBeNull();
    });

    it("should not setup timer when no access token", () => {
      useAuthStore.setState({
        accessToken: null,
        refreshToken: "refresh-token",
        isAuthenticated: true,
        webSocketConnected: true,
      });

      useAuthStore.getState().setupProactiveRefresh();

      expect(useAuthStore.getState().refreshTimerId).toBeNull();
    });

    it("should handle invalid token gracefully", () => {
      const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      useAuthStore.setState({
        accessToken: "invalid-token",
        refreshToken: "refresh-token",
        isAuthenticated: true,
        webSocketConnected: true,
      });

      useAuthStore.getState().setupProactiveRefresh();

      expect(useAuthStore.getState().refreshTimerId).toBeNull();
      expect(consoleSpy).toHaveBeenCalledWith(
        "Could not determine token expiry - skipping proactive refresh"
      );

      consoleSpy.mockRestore();
    });

    it("should clear session when token is already expired", () => {
      const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      // Create a token that expired 1 minute ago
      const pastExpiry = Math.floor(Date.now() / 1000) - 60;
      const mockToken = createMockToken(pastExpiry);

      useAuthStore.setState({
        accessToken: mockToken,
        refreshToken: "refresh-token",
        isAuthenticated: true,
        webSocketConnected: true,
      });

      useAuthStore.getState().setupProactiveRefresh();

      expect(useAuthStore.getState().isAuthenticated).toBe(false);
      expect(consoleSpy).toHaveBeenCalledWith("Token already expired - clearing session");

      consoleSpy.mockRestore();
    });
  });

  describe("timer scheduling", () => {
    it("test_refresh_runs_five_minutes_before_token_expiry", async () => {
      const timeoutSpy = vi.spyOn(globalThis, "setTimeout");
      // Create a token that expires in 20 minutes
      const futureExpiry = Math.floor(Date.now() / 1000) + 20 * 60;
      const mockToken = createMockToken(futureExpiry);
      const refreshedExpiry = Math.floor(Date.now() / 1000) + 60 * 60;
      authRuntimeMocks.refreshSessionTokens.mockResolvedValue({
        access_token: createMockToken(refreshedExpiry),
        refresh_token: "next-refresh-token",
      });

      useAuthStore.getState().setSession({
        accessToken: mockToken,
        refreshToken: "refresh-token",
        user: { id: 1 },
      });

      useAuthStore.getState().setWebSocketConnected(true);

      // Should schedule refresh for 15 minutes from now (20 - 5)
      expect(useAuthStore.getState().refreshTimerId).not.toBeNull();
      const refreshTimers = timeoutSpy.mock.calls.filter(([, delay]) => (
        typeof delay === "number" && delay >= 14 * 60 * 1000
      ));
      expect(refreshTimers).toHaveLength(1);
      await vi.advanceTimersByTimeAsync(14 * 60 * 1000);
      expect(authRuntimeMocks.refreshSessionTokens).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(60 * 1000);
      await vi.waitFor(() => {
        expect(authRuntimeMocks.refreshSessionTokens).toHaveBeenCalledOnce();
      });
      expect(authRuntimeMocks.refreshSessionTokens).toHaveBeenCalledWith("refresh-token");
      expect(useAuthStore.getState().refreshToken).toBe("next-refresh-token");
      expect(useAuthStore.getState().refreshTimerId).not.toBeNull();
      const scheduledRefreshes = timeoutSpy.mock.calls.filter(([, delay]) => (
        typeof delay === "number" && delay >= 14 * 60 * 1000
      ));
      expect(scheduledRefreshes).toHaveLength(2);
      timeoutSpy.mockRestore();
    });

    it("test_near_expiry_token_pings_immediately_without_a_timer", async () => {
      const timerCountBefore = vi.getTimerCount();
      // Create a token that expires in 3 minutes
      const futureExpiry = Math.floor(Date.now() / 1000) + 3 * 60;
      const mockToken = createMockToken(futureExpiry);
      authRuntimeMocks.pingAuthenticatedSession.mockResolvedValue(undefined);

      useAuthStore.setState({
        accessToken: mockToken,
        refreshToken: "refresh-token",
        isAuthenticated: true,
        webSocketConnected: true,
      });

      useAuthStore.getState().setupProactiveRefresh();

      // Should not set a timer since refresh is immediate
      expect(useAuthStore.getState().refreshTimerId).toBeNull();
      expect(vi.getTimerCount()).toBe(timerCountBefore);
      await vi.waitFor(() => {
        expect(authRuntimeMocks.pingAuthenticatedSession).toHaveBeenCalledWith(mockToken);
      });
    });

    it("test_near_expiry_ping_rejection_is_handled", async () => {
      const futureExpiry = Math.floor(Date.now() / 1000) + 3 * 60;
      const mockToken = createMockToken(futureExpiry);
      authRuntimeMocks.pingAuthenticatedSession.mockRejectedValue(new Error("network unavailable"));

      useAuthStore.setState({
        accessToken: mockToken,
        refreshToken: "refresh-token",
        isAuthenticated: true,
        webSocketConnected: true,
      });

      useAuthStore.getState().setupProactiveRefresh();

      await vi.waitFor(() => {
        expect(authRuntimeMocks.pingAuthenticatedSession).toHaveBeenCalledOnce();
      });
      expect(useAuthStore.getState().refreshTimerId).toBeNull();
    });
  });
});
