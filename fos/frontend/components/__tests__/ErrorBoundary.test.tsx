/**
 * This file checks that page errors leave a useful message on screen.
 *
 * The test makes sure ErrorBoundary catches a render failure and offers a retry button.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "../ErrorBoundary";

function BrokenPage(): React.ReactNode {
  throw new TypeError("Page failed to render");
}

describe("ErrorBoundary", () => {
  it("shows recovery controls when a page fails to render", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <ErrorBoundary>
        <BrokenPage />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Page failed to render");
    expect(screen.getByRole("button", { name: "components.errorBoundary.retry" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "components.errorBoundary.reload" })).toBeInTheDocument();
  });
});
