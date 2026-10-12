/**
 * These tests make sure the simulation tree keeps branch controls in the
 * tree panel and removes the old dynamic events toggle from that header.
 *
 * Each test checks one visible tree action.
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SimTree } from "../SimTree";
import { useSimulationStore } from "../../store";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      (
        {
          "components.simTree.title": "Simulation Tree",
          "components.simTree.legendHelp": "Legend",
          "components.simTree.selectCompareNode": "Select compare node",
          "components.simTree.clickToCompare": "Click to compare",
          "components.simTree.baseline": "Baseline",
          "components.simTree.compare": "Compare",
          "components.simTree.frontier": "Frontier",
          "components.simTree.selected": "Selected",
          "components.simTree.failed": "Failed",
          "components.simTree.zoomIn": "Zoom in",
          "components.simTree.zoomOut": "Zoom out",
          "components.simTree.resetView": "Reset view",
          "components.simTree.confirmDelete": "Delete this branch?",
          "components.simTree.deleteNode": "Delete branch",
          "components.sidebar.overviewHint": "Overview hint",
          "simPage.branch": "Create branch",
        } as Record<string, string>
      )[key] ?? key,
  }),
}));

describe("SimTree", () => {
  beforeEach(() => {
    Object.defineProperty(globalThis.SVGSVGElement.prototype, "width", {
      configurable: true,
      value: { baseVal: { value: 800 } },
    });
    Object.defineProperty(globalThis.SVGSVGElement.prototype, "height", {
      configurable: true,
      value: { baseVal: { value: 600 } },
    });

    useSimulationStore.setState({
      nodes: [
        {
          id: "1",
          display_id: "1",
          parentId: null,
          name: "Root",
          depth: 0,
          isLeaf: true,
          status: "completed",
          timestamp: "10:00",
          worldTime: "2026-05-21T10:00:00.000Z",
          meta: {},
        },
      ],
      selectedNodeId: "1",
      compareTargetNodeId: null,
      isCompareMode: false,
      branchSimulation: vi.fn(),
      selectNode: vi.fn(),
      setCompareTarget: vi.fn(),
      toggleHelpModal: vi.fn(),
      deleteNode: vi.fn(),
      environmentEnabled: true,
      toggleEnvironmentEnabled: vi.fn(),
      environmentSuggestionsAvailable: false,
      environmentSuggestions: [],
      environmentSuggestionsLoading: false,
      checkEnvironmentSuggestions: vi.fn(),
      generateEnvironmentSuggestions: vi.fn(),
      applyEnvironmentSuggestion: vi.fn(),
      dismissEnvironmentSuggestions: vi.fn(),
      currentSimulation: { id: "sim-1" },
    } as never);
  });

  it("shows create branch in the tree panel and triggers branching from there", () => {
    render(<SimTree layoutDirection="vertical" />);

    const branchButton = screen.getByRole("button", { name: "Create branch" });
    fireEvent.click(branchButton);

    expect(branchButton).toBeInTheDocument();
    expect(useSimulationStore.getState().branchSimulation).toHaveBeenCalledTimes(1);
  });

  it("does not show the dynamic events toggle in the tree header", () => {
    render(<SimTree layoutDirection="vertical" />);

    expect(screen.queryByText("Dynamic Events")).not.toBeInTheDocument();
  });
});
