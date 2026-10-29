/**
 * These tests make sure the left rail only opens hover preview for the
 * tabs that should support it right now.
 *
 * Each test checks one simple hover behavior.
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TabRail } from "../TabRail";
import { useSimulationStore } from "../../store";

vi.useFakeTimers();

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      (
        {
          "simPage.tabs.workspace": "Workspace",
          "simPage.tabs.agents": "Agents",
          "simPage.tabs.intervention": "Intervention",
          "simPage.tabs.analyse": "Analyse",
          "simPage.more": "More",
          "simPage.moreActions": "More actions",
          "simPage.provider": "Provider",
          "simPage.selectProvider": "Select provider",
          "simPage.globalKnowledge": "Global Knowledge Base",
          "simPage.analytics": "Analytics",
          "simPage.report": "Report",
          "simPage.export": "Export",
          "simPage.resetSimulation": "Reset",
          "simPage.deleteSimulation": "Delete experiment...",
          "simPage.confirmReset": "Reset this simulation?",
          "simPage.confirmDelete": "Delete this simulation?",
        } as Record<string, string>
      )[key] ?? key,
  }),
}));

describe("TabRail", () => {
  const confirmMock = vi.fn();

  beforeEach(() => {
    confirmMock.mockReset();
    vi.stubGlobal("confirm", confirmMock);
    useSimulationStore.setState({
      currentSimulation: { id: "sim-1", name: "Test simulation" },
      activeTab: "workspace",
      peekTab: null,
      peekOverlayActive: false,
      llmProviders: [],
      selectedProviderId: null,
      currentProviderId: null,
      setSelectedProvider: vi.fn(),
      toggleAnalytics: vi.fn(),
      toggleExport: vi.fn(),
      toggleReportModal: vi.fn(),
      setGlobalKnowledgeOpen: vi.fn(),
      resetSimulation: vi.fn(() => Promise.resolve()),
      deleteSimulation: vi.fn(() => Promise.resolve()),
      isGenerating: false,
    } as never);
  });

  it("opens hover preview for the agents tab", () => {
    render(<TabRail width={96} />);

    expect(screen.getByText("Workspace")).toBeInTheDocument();
    expect(screen.getByText("Agents")).toBeInTheDocument();
    fireEvent.mouseEnter(screen.getByTitle("Agents"));
    vi.advanceTimersByTime(350);

    expect(useSimulationStore.getState().peekTab).toBe("agents");
  });

  it("does not open hover preview for the intervention tab", () => {
    render(<TabRail width={96} />);

    fireEvent.mouseEnter(screen.getByTitle("Intervention"));
    vi.advanceTimersByTime(350);

    expect(useSimulationStore.getState().peekTab).toBeNull();
  });

  it("shows the more actions button below the analyse tab", () => {
    render(<TabRail width={96} />);

    const buttons = screen.getAllByRole("button");
    expect(buttons.at(-2)).toHaveAttribute("title", "Analyse");
    expect(buttons.at(-1)).toHaveAttribute("aria-label", "More");
    expect(buttons.at(-1)).toHaveTextContent("More");
  });

  it("opens the moved more actions menu from the rail", () => {
    render(<TabRail width={96} />);

    fireEvent.click(screen.getByRole("button", { name: "More" }));

    expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete experiment..." })).toBeInTheDocument();
  });
});
