/**
 * This file checks the host panel path for external events.
 *
 * Each test here does one simple job:
 * - it opens the External Events section,
 * - it loads rows from the backend client,
 * - it applies one event through the real panel wiring.
 */

import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { HostPanel } from "../HostPanel";
import { useSimulationStore } from "../../store";
import { apiClient } from "../../services/client";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

vi.mock("../MultimodalInput", () => ({
  MultimodalInput: () => <div>Image input</div>,
}));

vi.mock("../InitialEventsModal", () => ({
  InitialEventsModal: () => <div>Initial events modal</div>,
}));

vi.mock("../RuleConfig", () => ({
  RuleConfig: () => <div>Rule config</div>,
}));

describe("HostPanel external events smoke test", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSimulationStore.setState({
      agents: [
        {
          id: "a-1",
          name: "Alice",
          role: "Citizen",
          properties: { trust: 5 },
          history: {},
          memory: [],
          knowledgeBase: [],
          avatarUrl: "",
          profile: "",
          llmConfig: { provider: "mock", model: "default" },
        },
      ],
      currentSimulation: {
        id: "SIM123",
        scene_type: "experiment_template",
      },
      selectedNodeId: "7",
      injectLog: vi.fn(),
      updateAgentProperty: vi.fn(),
      addNotification: vi.fn(),
      toggleInitialEvents: vi.fn(),
    } as never);

    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        events: [
          {
            id: "evt-1",
            event_type: "news",
            source: "news-feed",
            title: "Supply Shock",
            content: "A sudden supply shock changes tomorrow's conditions.",
            timestamp: "2026-01-04T10:00:00",
            severity: "high",
            status: "pending",
          },
        ],
      },
    } as never);

    vi.mocked(apiClient.post).mockResolvedValue({
      data: {
        success: true,
        event_id: "evt-1",
        message: "Applied",
      },
    } as never);
  });

  it("opens external events, fetches rows, and applies one event", async () => {
    render(<HostPanel />);

    fireEvent.click(screen.getByText("components.hostPanel.externalEvents"));

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalled();
      expect(screen.getByText("Supply Shock")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "components.event.apply" }));

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalled();
    });
  });
});
