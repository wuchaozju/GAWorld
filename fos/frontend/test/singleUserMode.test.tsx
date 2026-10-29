/**
 * Phase 2 (task 2497) single-user mode tests.
 *
 * RED tests: with single_user_mode=true (as exposed by the config/bootstrap
 * endpoint), RequireAuth must NOT redirect to /login — the app proceeds with
 * the local user. GUARD tests pin today's behaviour when it is false.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// test/setup.ts globally mocks ../services/simulationTree; restore the real
// module so we can exercise the actual WebSocket URL derivation.
vi.mock("../services/simulationTree", async (importOriginal) => await importOriginal());

import { RequireAuth } from "../components/RequireAuth";
import { useAuthStore } from "../store/auth";
import { getApiBase } from "../services/base";
import { connectTreeEvents } from "../services/simulationTree";

function mockConfig(singleUserMode: boolean) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ app_name: "FOS", single_user_mode: singleUserMode }),
  });
}

function renderProtected() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route
          path="/"
          element={
            <RequireAuth>
              <div>Protected page</div>
            </RequireAuth>
          }
        />
        <Route path="/login" element={<div>Login page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("single_user_mode (Phase 2)", () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      user: null,
      hasRestored: true, // session restore already settled; unauthenticated
      restoreSession: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("RED: does not redirect to /login when single_user_mode=true", async () => {
    vi.stubGlobal("fetch", mockConfig(true));
    renderProtected();
    await waitFor(() => {
      expect(screen.getByText("Protected page")).toBeInTheDocument();
    });
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });

  it("GUARD: redirects to /login when single_user_mode=false and signed out", async () => {
    vi.stubGlobal("fetch", mockConfig(false));
    renderProtected();
    await waitFor(() => {
      expect(screen.getByText("Login page")).toBeInTheDocument();
    });
    expect(screen.queryByText("Protected page")).not.toBeInTheDocument();
  });

  it("GUARD: signed-in users see the protected page when single_user_mode=false", () => {
    vi.stubGlobal("fetch", mockConfig(false));
    useAuthStore.setState({ isAuthenticated: true, user: { id: 1 } });
    renderProtected();
    expect(screen.getByText("Protected page")).toBeInTheDocument();
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });
});

describe("API base / WebSocket derivation for the integrated /fos prefix", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("GUARD: VITE_API_BASE_URL=/fos/api is used verbatim as the API base", () => {
    vi.stubEnv("VITE_API_BASE_URL", "/fos/api");
    expect(getApiBase()).toBe("/fos/api");
  });

  it("GUARD: WebSocket URL keeps the /fos/api prefix and the ws scheme", () => {
    const seen: string[] = [];
    class FakeWebSocket {
      static OPEN = 1;
      url: string;
      constructor(url: string) {
        this.url = url;
        seen.push(url);
      }
      close() {}
    }
    vi.stubGlobal("WebSocket", FakeWebSocket);

    connectTreeEvents("/fos/api", "7", "tok", () => {});
    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatch(/^ws:/);
    expect(seen[0]).toContain("/fos/api/simulations/7/tree/events");
  });
});
