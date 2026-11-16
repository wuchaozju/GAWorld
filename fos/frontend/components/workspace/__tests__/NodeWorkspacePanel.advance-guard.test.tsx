/**
 * Task 2913 — the Advance button is disabled while the selected node is
 * known to be running (graph.running → node status 'running'), not only
 * while a request is pending (isGenerating).
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NodeWorkspacePanel } from "../NodeWorkspacePanel";
import { useSimulationStore } from "../../../store";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

function renderPanel() {
  return render(
    <NodeWorkspacePanel
      onRequestCreateBranch={vi.fn()}
      onToggleBranchDetails={vi.fn()}
      workspaceMode="control"
    >
      null
    </NodeWorkspacePanel>,
  );
}

describe("Advance button disabled while node is running", () => {
  beforeEach(() => {
    useSimulationStore.setState({
      nodes: [
        { id: "0", parentId: null, name: "Node 0", depth: 0, isLeaf: false, status: "completed" },
      ],
      selectedNodeId: "0",
      currentSimulation: { id: "sim-1" },
      llmProviders: [],
      selectedProviderId: null,
      currentProviderId: null,
      isCompareMode: false,
      isGenerating: false,
      advanceSimulation: vi.fn(),
      selectNode: vi.fn(),
      setCompareTarget: vi.fn(),
    } as never);
  });

  it("is enabled for a completed node with no pending request", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: /controlRoom\.continueSimulation|simulationWorkspace\.running/ })).toBeEnabled();
  });

  it("is disabled while a request is pending (isGenerating)", () => {
    useSimulationStore.setState({ isGenerating: true } as never);
    renderPanel();
    expect(screen.getByRole("button", { name: /controlRoom\.continueSimulation|simulationWorkspace\.running/ })).toBeDisabled();
  });

  it("is disabled when the selected node status is 'running'", () => {
    useSimulationStore.setState({
      nodes: [
        { id: "0", parentId: null, name: "Node 0", depth: 0, isLeaf: false, status: "running" },
      ],
    } as never);
    renderPanel();
    expect(screen.getByRole("button", { name: /controlRoom\.continueSimulation|simulationWorkspace\.running/ })).toBeDisabled();
  });
});
