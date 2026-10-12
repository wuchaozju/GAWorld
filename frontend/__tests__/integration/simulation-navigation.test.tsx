/**
 * These tests make sure the simulation page uses the new left rail and
 * shows the right area when each main tab is chosen.
 *
 * Each test checks one simple thing a person can see on the page.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import SimulationPage from "../../pages/SimulationPage";
import { useSimulationStore } from "../../store";
import { useAuthStore } from "../../store/auth";

const translations: Record<string, string> = {
  "simPage.tabs.workspace": "Workspace",
  "simPage.tabs.agents": "Agents",
  "simPage.tabs.intervention": "Intervention",
  "simPage.tabs.analyse": "Analyse",
  "simPage.analytics": "Analytics",
  "simPage.report": "Report",
};

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => translations[key] ?? key,
    i18n: { language: "en", changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

vi.mock("../../components/SimTree", () => ({
  SimTree: () => <div>Sim Tree Panel</div>,
}));

vi.mock("../../components/Sidebar", () => ({
  Sidebar: () => <div>Agents Panel</div>,
}));

vi.mock("../../components/LogViewer", () => ({
  LogViewer: () => <div>Log Viewer Panel</div>,
}));

vi.mock("../../components/ComparisonView", () => ({
  ComparisonView: () => <div>Comparison Panel</div>,
}));

vi.mock("../../components/ContextToolbar", () => ({
  default: () => null,
}));

vi.mock("../../components/PeekOverlay", () => ({
  PeekOverlay: () => <div>Peek Overlay</div>,
}));

vi.mock("../../components/InterventionTab", () => ({
  InterventionTab: () => <div>Intervention Panel</div>,
}));

vi.mock("../../components/AnalyseTab", () => ({
  AnalyseTab: () => <div>Analyse Panel</div>,
}));

vi.mock("../../components/ExperimentBuilderModal", () => ({
  ExperimentBuilderModal: () => null,
}));

vi.mock("../../components/SyncModal", () => ({
  SyncModal: () => null,
}));

vi.mock("../../components/HelpModal", () => ({
  HelpModal: () => null,
}));

vi.mock("../../components/AnalyticsPanel", () => ({
  AnalyticsPanel: () => null,
}));

vi.mock("../../components/ExportModal", () => ({
  ExportModal: () => null,
}));

vi.mock("../../components/ExperimentDesignModal", () => ({
  ExperimentDesignModal: () => null,
}));

vi.mock("../../components/TimeSettingsModal", () => ({
  TimeSettingsModal: () => null,
}));

vi.mock("../../components/TemplateSaveModal", () => ({
  TemplateSaveModal: () => null,
}));

vi.mock("../../components/NetworkEditorModal", () => ({
  NetworkEditorModal: () => null,
}));

vi.mock("../../components/ReportModal", () => ({
  ReportModal: () => null,
}));

vi.mock("../../components/GlobalKnowledgePanel", () => ({
  GlobalKnowledgePanel: () => null,
}));

vi.mock("../../components/GuideAssistant", () => ({
  GuideAssistant: () => null,
}));

vi.mock("../../components/Toast", () => ({
  ToastContainer: () => null,
}));

const renderPage = () =>
  render(
    <MemoryRouter>
      <SimulationPage />
    </MemoryRouter>
  );

describe("Simulation page navigation", () => {
  beforeEach(() => {
    useSimulationStore.setState({
      activeTab: "workspace",
      isCompareMode: false,
      currentSimulation: { id: "sim-1", name: "Test Sim" },
      nodes: [{ id: "node-1", parentId: null, name: "Root", depth: 0, isLeaf: true }],
      selectedNodeId: "node-1",
      agents: [],
      logs: [],
      rawEvents: [],
    } as never);

    useAuthStore.setState({
      isAuthenticated: false,
      hasRestored: true,
    });
  });

  it("shows the workspace rail button and opens the workspace first", async () => {
    renderPage();

    expect(screen.getByTitle("Workspace")).toBeInTheDocument();
    expect(screen.getByTitle("Agents")).toBeInTheDocument();
    expect(screen.getByTitle("Intervention")).toBeInTheDocument();
    expect(screen.getByTitle("Analyse")).toBeInTheDocument();
    expect(screen.getByText("Sim Tree Panel")).toBeInTheDocument();
    expect(await screen.findByText("Log Viewer Panel")).toBeInTheDocument();
  });

  it("shows the intervention area when the intervention rail button is pressed", async () => {
    renderPage();

    fireEvent.click(screen.getByTitle("Intervention"));

    expect(await screen.findByText("Intervention Panel")).toBeInTheDocument();
    expect(screen.queryByText("Sim Tree Panel")).not.toBeInTheDocument();
  });

  it("shows the analyse area when the analyse rail button is pressed", async () => {
    renderPage();

    fireEvent.click(screen.getByTitle("Analyse"));

    expect(await screen.findByText("Analyse Panel")).toBeInTheDocument();
    expect(screen.queryByText("Sim Tree Panel")).not.toBeInTheDocument();
  });
});
