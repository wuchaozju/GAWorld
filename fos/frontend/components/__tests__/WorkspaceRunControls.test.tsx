/**
 * These tests check the compact run controls in the live workspace.
 *
 * They make sure the top-right control row keeps the advance tools,
 * while the extra actions menu can move elsewhere during design tests.
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceRunControls } from "../WorkspaceRunControls";
import { useSimulationStore } from "../../store";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      (
        {
          "simPage.advance": "Advance node",
          "simPage.stop": "Stop",
          "simPage.enterSteps": "Enter steps",
          "sim.running": "Running",
          "sim.agents": "Agents",
        } as Record<string, string>
      )[key] ?? key,
  }),
}));

describe("WorkspaceRunControls", () => {
  beforeEach(() => {
    useSimulationStore.setState({
      currentSimulation: { id: "sim-1", name: "Test simulation" },
      selectedNodeId: "1",
      isGenerating: false,
      isCompareMode: false,
      isAutoAdvancing: false,
      autoAdvanceCurrent: 0,
      autoAdvanceTotal: 0,
      agents: [],
      startAutoAdvance: vi.fn(),
      stopAutoAdvance: vi.fn(),
    } as never);
  });

  it("does not show the more actions button in the top-right controls", () => {
    render(<WorkspaceRunControls compact />);

    expect(screen.queryByRole("button", { name: "More actions" })).not.toBeInTheDocument();
  });

  it("keeps the advance controls visible", () => {
    render(<WorkspaceRunControls compact />);

    expect(screen.getByRole("button", { name: "Advance node" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Enter steps" })).toBeInTheDocument();
  });

  it("lets a policy erosion simulation advance from the selected root node", () => {
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

    render(<WorkspaceRunControls compact />);

    const advanceButton = screen.getByRole("button", { name: "Advance node" });

    expect(advanceButton).toBeEnabled();

    fireEvent.click(advanceButton);

    expect(startAutoAdvance).toHaveBeenCalledOnce();
    expect(startAutoAdvance).toHaveBeenCalledWith(1);
  });
});
