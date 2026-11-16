/**
 * These tests make sure the old workspace toolbar does not appear.
 *
 * Each test checks one visible thing that should stay out of the page.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ContextToolbar from "../ContextToolbar";
import { useSimulationStore } from "../../store";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      (
        {
          "simPage.advance": "Advance node",
          "simPage.advanceControls": "Advance Controls",
          "simPage.branch": "Create branch",
          "simPage.autoAdvance": "Auto advance",
          "simPage.enterSteps": "Enter steps",
          "simPage.designExperiment": "Design experiment",
          "simPage.compareMode": "Compare mode",
          "simPage.analytics": "Analytics",
          "simPage.report": "Report",
          "simPage.export": "Export",
          "simPage.provider": "Provider",
          "simPage.globalKnowledge": "Global knowledge",
          "simPage.moreActions": "More actions",
          "simPage.selectProvider": "Select provider",
          "sim.running": "Running",
          "sim.agents": "Agents",
        } as Record<string, string>
      )[key] ?? key,
  }),
}));

describe("ContextToolbar", () => {
  beforeEach(() => {
    useSimulationStore.setState({
      activeTab: "workspace",
      selectedNodeId: "1",
      isGenerating: false,
      isCompareMode: false,
      isAutoAdvancing: false,
      autoAdvanceCurrent: 0,
      autoAdvanceTotal: 0,
      agents: [],
      llmProviders: [],
      selectedProviderId: null,
      currentProviderId: null,
      advanceSimulation: vi.fn(),
      branchSimulation: vi.fn(),
      startAutoAdvance: vi.fn(),
      stopAutoAdvance: vi.fn(),
      toggleCompareMode: vi.fn(),
      setCompareTarget: vi.fn(),
      toggleExperimentDesigner: vi.fn(),
      toggleAnalytics: vi.fn(),
      toggleExport: vi.fn(),
      toggleReportModal: vi.fn(),
      setGlobalKnowledgeOpen: vi.fn(),
      setSelectedProvider: vi.fn(),
    } as never);
  });

  it("does not show the left toolbar overflow button", () => {
    render(<ContextToolbar />);

    expect(screen.queryByRole("button", { name: "More actions" })).not.toBeInTheDocument();
    expect(screen.queryByText("Analytics")).not.toBeInTheDocument();
    expect(screen.queryByText("Report")).not.toBeInTheDocument();
    expect(screen.queryByText("Export")).not.toBeInTheDocument();
    expect(screen.queryByText("Global knowledge")).not.toBeInTheDocument();
  });

  it("does not show the duplicate advance controls in the left toolbar", () => {
    render(<ContextToolbar />);

    expect(screen.queryByLabelText("Advance Controls")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Advance node" })).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton", { name: "Enter steps" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Auto advance" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create branch" })).not.toBeInTheDocument();
  });

  it("does not show running status or agent count in the left toolbar", () => {
    useSimulationStore.setState({
      isGenerating: true,
      agents: new Array(1247).fill(null).map((_, index) => ({
        id: `agent-${index}`,
        name: `Agent ${index}`,
      })),
    } as never);

    render(<ContextToolbar />);

    expect(screen.queryByText("Running")).not.toBeInTheDocument();
    expect(screen.queryByText("1,247 Agents")).not.toBeInTheDocument();
  });

  it("keeps policy erosion advance out of the left toolbar", () => {
    const startAutoAdvance = vi.fn();
    useSimulationStore.setState({
      currentSimulation: {
        id: "policy-sim-1",
        name: "Policy erosion",
        scenario_id: "policy_erosion",
        scene_type: "policy_cascade_scene",
      },
      selectedNodeId: "root",
      startAutoAdvance,
    } as never);

    render(<ContextToolbar />);

    expect(screen.queryByRole("button", { name: "Advance node" })).not.toBeInTheDocument();
    expect(startAutoAdvance).not.toHaveBeenCalled();
  });
});
