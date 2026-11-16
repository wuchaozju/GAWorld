/**
 * These tests make sure the agents page shows the two main views people
 * expect: the agent watch list and the network view.
 *
 * Each test checks one visible page switch.
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "../Sidebar";
import { useSimulationStore } from "../../store";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      (
        {
          "components.sidebar.agentWatch": "Agent watch",
          "simPage.network": "Network",
          "experimentBuilder.step5.networkPresets": "Network presets",
          "experimentBuilder.step5.manualLinks": "Manual links",
        } as Record<string, string>
      )[key] ?? key,
  }),
}));

vi.mock("../AgentPanel", () => ({
  AgentPanel: () => <div>Agent Watch Panel</div>,
}));

vi.mock("../NetworkGraph", () => ({
  default: () => <div>Network Panel</div>,
}));

describe("Sidebar", () => {
  beforeEach(() => {
    useSimulationStore.setState({
      agents: [
        { id: "a-1", name: "Mayor", role: "Leader", properties: {}, history: {}, memory: [], knowledgeBase: [], avatarUrl: "", profile: "", llmConfig: { provider: "mock", model: "default" } },
      ],
      currentSimulation: {
        id: "sim-1",
        name: "Test Sim",
        socialNetwork: { Mayor: [] },
      },
    } as never);
  });

  it("shows the agent watch view first", () => {
    render(<Sidebar />);

    expect(screen.getByText("Agent watch")).toBeInTheDocument();
    expect(screen.getByText("Network")).toBeInTheDocument();
    expect(screen.getByText("Agent Watch Panel")).toBeInTheDocument();
  });

  it("switches to the network view when the network tab is pressed", () => {
    render(<Sidebar />);

    fireEvent.click(screen.getByRole("button", { name: "Network" }));

    expect(screen.getByText("Network Panel")).toBeInTheDocument();
  });

  it("shows network tools in the network view", () => {
    render(<Sidebar />);

    fireEvent.click(screen.getByRole("button", { name: "Network" }));

    expect(screen.getByText("Network presets")).toBeInTheDocument();
    expect(screen.getByText("Manual links")).toBeInTheDocument();
  });
});
