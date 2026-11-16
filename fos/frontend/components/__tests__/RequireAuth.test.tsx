/**
 * This file checks that protected pages always show something while login details are restored.
 *
 * The test makes sure RequireAuth shows a loading message instead of an empty screen.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RequireAuth } from "../RequireAuth";
import { useAuthStore } from "../../store/auth";

describe("RequireAuth", () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      user: null,
      hasRestored: false,
      restoreSession: vi.fn(),
    });
  });

  it("shows a loading message while login details are restored", () => {
    render(
      <MemoryRouter>
        <RequireAuth>
          <div>Protected page</div>
        </RequireAuth>
      </MemoryRouter>,
    );

    expect(screen.getByRole("status")).toHaveTextContent("common.loading");
  });
});
