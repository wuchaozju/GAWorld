/**
 * These tests make sure peek panels do not leave hidden workspace controls
 * mounted on the page.
 *
 * Each test checks whether the hidden copy can still be found.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSimulationStore } from "../../store";
import { PeekOverlay } from "../PeekOverlay";

vi.mock("../SimTree", () => ({
  SimTree: () => <div>Tree preview</div>,
}));

vi.mock("../LogViewer", () => ({
  LogViewer: () => <button type="button">Advance node</button>,
}));

vi.mock("../Sidebar", () => ({
  Sidebar: () => <div>Agents preview</div>,
}));

describe("PeekOverlay", () => {
  beforeEach(() => {
    useSimulationStore.setState({
      peekTab: null,
      setPeekTab: vi.fn(),
      setPeekOverlayActive: vi.fn(),
    } as never);
  });

  it("does not mount hidden workspace controls when no tab is being peeked", () => {
    render(<PeekOverlay />);

    expect(screen.queryByRole("button", { name: "Advance node" })).not.toBeInTheDocument();
  });

  it("mounts workspace controls only while the workspace tab is being peeked", () => {
    useSimulationStore.setState({ peekTab: "workspace" } as never);

    render(<PeekOverlay />);

    expect(screen.getByRole("button", { name: "Advance node" })).toBeInTheDocument();
  });
});
