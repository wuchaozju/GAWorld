/**
 * These tests make sure the log viewer stays on its default layout
 * without showing inactive view-switch buttons.
 *
 * Each test checks one simple thing a person can see.
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LogViewer } from "../LogViewer";
import { useSimulationStore } from "../../store";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      (
        {
          "components.logViewer.currentBranchFilter": "Current branch",
          "components.logViewer.searchPlaceholder": "Search logs",
          "components.logViewer.noMatchingLogs": "No matching logs found",
          "components.logViewer.noActivityYet": "No activity yet",
          "components.logViewer.showingRecords": `Showing ${options?.count ?? 0} records`,
          "components.logViewer.stepGroup": `Step ${options?.step ?? ""}`,
          "components.logViewer.setupGroup": "Setup",
          "components.logViewer.agentOutputProgress": `${options?.finished ?? 0} of ${options?.total ?? 0} agents reported`,
          "components.logViewer.listView": "List view",
          "components.logViewer.cardView": "Card view",
          "components.logViewer.timelineView": "Timeline view",
          "simPage.advance": "Advance node",
          "simPage.stop": "Stop",
          "simPage.enterSteps": "Enter steps",
          "simPage.moreActions": "More actions",
          "simPage.provider": "Provider",
          "simPage.selectProvider": "Select provider",
          "simPage.globalKnowledge": "Global knowledge",
          "simPage.analytics": "Analytics",
          "simPage.report": "Report",
          "simPage.export": "Export",
          "sim.running": "Running",
          "sim.agents": "Agents",
        } as Record<string, string>
      )[key] ?? key,
  }),
}));

describe("LogViewer", () => {
  const baseState = {
    isGenerating: false,
    isCompareMode: false,
    isAutoAdvancing: false,
    autoAdvanceCurrent: 0,
    autoAdvanceTotal: 0,
    llmProviders: [],
    selectedProviderId: null,
    currentProviderId: null,
    startAutoAdvance: vi.fn(),
    stopAutoAdvance: vi.fn(),
    toggleAnalytics: vi.fn(),
    toggleExport: vi.fn(),
    toggleReportModal: vi.fn(),
    setGlobalKnowledgeOpen: vi.fn(),
    setSelectedProvider: vi.fn(),
  };

  it("does not show the old view mode buttons", () => {
    useSimulationStore.setState({
      ...baseState,
      logs: [],
      nodes: [],
      selectedNodeId: "root",
      agents: [],
      currentSimulation: null,
    } as never);

    render(<LogViewer />);

    expect(screen.queryByTitle("List view")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Card view")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Timeline view")).not.toBeInTheDocument();
    expect(screen.queryByText("Current branch")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Filter" })).not.toBeInTheDocument();
    expect(screen.getByText("No matching logs found")).toBeInTheDocument();
  });

  it("shows the right side advance node button inside the log viewer", () => {
    useSimulationStore.setState({
      ...baseState,
      logs: [],
      nodes: [],
      selectedNodeId: "root",
      agents: [{ id: "agent-1", name: "Agent 1" }],
      currentSimulation: null,
    } as never);

    render(<LogViewer />);

    expect(screen.getByRole("button", { name: "Advance node" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Enter steps" })).toBeInTheDocument();
  });

  it("lets people keep multiple step groups open at the same time", () => {
    useSimulationStore.setState({
      ...baseState,
      logs: [
        {
          id: "log-4",
          nodeId: "node-1",
          round: 4,
          type: "SYSTEM",
          content: "Agents acted in step 4",
          timestamp: "2026-05-21T10:00:00.000Z",
        },
        {
          id: "log-5",
          nodeId: "node-1",
          round: 5,
          type: "SYSTEM",
          content: "Agents acted in step 5",
          timestamp: "2026-05-21T10:05:00.000Z",
        },
      ],
      nodes: [{ id: "node-1", parentId: null, name: "Root", depth: 0, isLeaf: true }],
      selectedNodeId: "node-1",
      agents: [],
      currentSimulation: null,
    } as never);

    render(<LogViewer />);

    expect(screen.getByText("Agents acted in step 4")).toBeInTheDocument();
    expect(screen.queryByText("Agents acted in step 5")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Step 5/i }));

    expect(screen.getByText("Agents acted in step 5")).toBeInTheDocument();
    expect(screen.getByText("Agents acted in step 4")).toBeInTheDocument();
  });

  it("lets people collapse all step groups after opening one", () => {
    useSimulationStore.setState({
      ...baseState,
      logs: [
        {
          id: "log-1",
          nodeId: "node-1",
          round: 1,
          type: "SYSTEM",
          content: "Agents acted in step 1",
          timestamp: "2026-05-21T10:00:00.000Z",
        },
        {
          id: "log-2",
          nodeId: "node-1",
          round: 2,
          type: "SYSTEM",
          content: "Agents acted in step 2",
          timestamp: "2026-05-21T10:05:00.000Z",
        },
      ],
      nodes: [{ id: "node-1", parentId: null, name: "Root", depth: 0, isLeaf: true }],
      selectedNodeId: "node-1",
      agents: [],
      currentSimulation: null,
    } as never);

    render(<LogViewer />);

    const stepOneButton = screen.getByRole("button", { name: /Step 1/i });

    expect(screen.getByText("Agents acted in step 1")).toBeInTheDocument();

    fireEvent.click(stepOneButton);

    expect(screen.queryByText("Agents acted in step 1")).not.toBeInTheDocument();
    expect(screen.queryByText("Agents acted in step 2")).not.toBeInTheDocument();
  });

  it("lists step groups in ascending order", () => {
    useSimulationStore.setState({
      ...baseState,
      logs: [
        {
          id: "log-2",
          nodeId: "node-1",
          round: 2,
          type: "SYSTEM",
          content: "Agents acted in step 2",
          timestamp: "2026-05-21T10:05:00.000Z",
        },
        {
          id: "log-1",
          nodeId: "node-1",
          round: 1,
          type: "SYSTEM",
          content: "Agents acted in step 1",
          timestamp: "2026-05-21T10:00:00.000Z",
        },
      ],
      nodes: [{ id: "node-1", parentId: null, name: "Root", depth: 0, isLeaf: true }],
      selectedNodeId: "node-1",
      agents: [],
      currentSimulation: null,
    } as never);

    render(<LogViewer />);

    const stepButtons = screen.getAllByRole("button", { name: /Step /i });
    expect(stepButtons[0]).toHaveTextContent("Step 1");
    expect(stepButtons[1]).toHaveTextContent("Step 2");
  });

  it("shows per-step agent progress using visible agent output", () => {
    useSimulationStore.setState({
      ...baseState,
      logs: [
        {
          id: "log-1",
          nodeId: "node-1",
          round: 1,
          type: "AGENT_ACTION",
          agentId: "agent-1",
          content: "Agent 1 acted",
          timestamp: "2026-05-21T10:00:00.000Z",
        },
        {
          id: "log-2",
          nodeId: "node-1",
          round: 1,
          type: "AGENT_SAY",
          agentId: "agent-2",
          content: "Agent 2 spoke",
          timestamp: "2026-05-21T10:01:00.000Z",
        },
      ],
      nodes: [{ id: "node-1", parentId: null, name: "Root", depth: 0, isLeaf: true }],
      selectedNodeId: "node-1",
      agents: [
        { id: "agent-1", name: "Agent 1" },
        { id: "agent-2", name: "Agent 2" },
        { id: "agent-3", name: "Agent 3" },
        { id: "agent-4", name: "Agent 4" },
      ],
      currentSimulation: null,
    } as never);

    render(<LogViewer />);

    expect(
      screen.getAllByText((content) => content.includes("2 of 4 agents reported")).length,
    ).toBeGreaterThan(0);
  });

  it("keeps the log search text clear of the search icon", () => {
    useSimulationStore.setState({
      ...baseState,
      logs: [],
      nodes: [],
      selectedNodeId: "root",
      agents: [],
      currentSimulation: null,
    } as never);

    render(<LogViewer />);

    const searchInput = screen.getByPlaceholderText("Search logs");
    const searchIcon = screen.getByTestId("log-search-icon");

    expect(searchInput).toHaveStyle({ paddingLeft: "2.875rem" });
    expect(searchIcon).toHaveStyle({ left: "0.875rem", pointerEvents: "none" });
  });
});
