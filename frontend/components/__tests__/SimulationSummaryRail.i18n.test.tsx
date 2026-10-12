/**
 * This file tests SimulationSummaryRail language behavior in runtime rendering.
 * renderSimulationSummaryRail renders the component with simple realistic store data.
 * test_simulation_summary_rail_shows_english_labels_by_default checks default English labels.
 * test_simulation_summary_rail_shows_chinese_labels_after_language_switch checks labels after switching to Chinese.
 * test_simulation_summary_rail_updates_labels_when_language_changes checks labels update after language change and rerender.
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SimulationSummaryRail } from "../workspace/SimulationSummaryRail";
import { resetLanguage, switchLanguage } from "../../test-utils/i18n";

type Language = "en" | "zh";

interface StoreState {
  currentSimulation: { name: string; scene_config: { description: string } };
  nodes: Array<{ id: string; display_id: string; depth: number; worldTime: string; parentId: string | null }>;
  logs: Array<{ id: string; nodeId: string }>;
  rawEvents: Array<{ id: string }>;
  agents: Array<{ id: string }>;
  selectedNodeId: string;
  selectedProviderId: string | null;
  currentProviderId: string | null;
  llmProviders: Array<{ id: string; name: string; provider: string; model: string }>;
  toggleTimeSettings: (value: boolean) => void;
  toggleReportModal: (value: boolean) => void;
  toggleExport: (value: boolean) => void;
  toggleSaveTemplate: (value: boolean) => void;
}

const mockNavigate = vi.fn();

let mockState: StoreState;

vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock("../../store", () => ({
  useSimulationStore: (selector: (state: StoreState) => unknown) => selector(mockState),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => {
    const language = (globalThis as unknown as { i18n: { language: Language } }).i18n.language;
    const translations: Record<Language, Record<string, string>> = {
      en: {
        "components.workspace.summaryRail.title": "Simulation Snapshot",
        "components.workspace.summaryRail.statusKicker": "Status summary",
        "components.workspace.summaryRail.headerSubtitle": "Keep only configuration, rules, metrics, and action shortcuts on the right side.",
        "components.workspace.summaryRail.worldModel": "World model",
        "components.workspace.summaryRail.branches": "Branches",
        "components.workspace.summaryRail.actions": "Actions",
        "components.workspace.summaryRail.actionsSubtitle": "Fast links for common workflows.",
        "components.workspace.summaryRail.systemMetrics": "System metrics",
        "components.workspace.summaryRail.saveTemplate": "Save as template",
        "components.workspace.summaryRail.openResearchLogs": "Open research logs",
        "components.workspace.summaryRail.pauseNote":
          "Pause or halt controls remain in the broader experiment controls while this rail stays focused on the stable actions available today.",
      },
      zh: {
        "components.workspace.summaryRail.title": "模拟快照",
        "components.workspace.summaryRail.statusKicker": "状态摘要",
        "components.workspace.summaryRail.headerSubtitle": "只保留最关键配置与操作入口。",
        "components.workspace.summaryRail.worldModel": "世界模型",
        "components.workspace.summaryRail.branches": "分支数",
        "components.workspace.summaryRail.actions": "操作",
        "components.workspace.summaryRail.actionsSubtitle": "常见流程的快速入口。",
        "components.workspace.summaryRail.systemMetrics": "系统指标",
        "components.workspace.summaryRail.saveTemplate": "保存为模板",
        "components.workspace.summaryRail.openResearchLogs": "打开研究日志",
        "components.workspace.summaryRail.pauseNote": "暂停 / 终止逻辑仍保留在系统设置与后续实验控制中，这里先保留当前稳定能力。",
      },
    };
    return {
      t: (key: string) => translations[language][key] ?? key,
      i18n: (globalThis as unknown as { i18n: { language: Language } }).i18n,
    };
  },
}));

function renderSimulationSummaryRail(): ReturnType<typeof render> {
  return render(
    <SimulationSummaryRail
      onHide={vi.fn()}
      onOpenLogs={vi.fn()}
    />
  );
}

describe("SimulationSummaryRail i18n", () => {
  beforeEach(async () => {
    await resetLanguage();
    mockState = {
      currentSimulation: {
        name: "Demo Simulation",
        scene_config: { description: "A stable world summary" },
      },
      nodes: [{ id: "node-1", display_id: "node-1", depth: 1, worldTime: "2026-05-22T10:00:00.000Z", parentId: null }],
      logs: [{ id: "log-1", nodeId: "node-1" }],
      rawEvents: [{ id: "event-1" }],
      agents: [{ id: "agent-1" }],
      selectedNodeId: "node-1",
      selectedProviderId: "provider-1",
      currentProviderId: "provider-1",
      llmProviders: [{ id: "provider-1", name: "GPT", provider: "OpenAI", model: "gpt-5" }],
      toggleTimeSettings: vi.fn(),
      toggleReportModal: vi.fn(),
      toggleExport: vi.fn(),
      toggleSaveTemplate: vi.fn(),
    };
  });

  afterEach(async () => {
    await resetLanguage();
  });

  it("test_simulation_summary_rail_shows_english_labels_by_default", () => {
    renderSimulationSummaryRail();
    expect(screen.getByText("Status summary")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Simulation Snapshot" })).toBeInTheDocument();
    expect(screen.getByText("Actions")).toBeInTheDocument();
    expect(screen.getByText("Fast links for common workflows.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /System metrics/ }));
    expect(screen.getByText("Branches")).toBeInTheDocument();
  });

  it("test_simulation_summary_rail_shows_chinese_labels_after_language_switch", async () => {
    await switchLanguage("zh");
    renderSimulationSummaryRail();
    expect(screen.getByText("状态摘要")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "模拟快照" })).toBeInTheDocument();
    expect(screen.getByText("操作")).toBeInTheDocument();
    expect(screen.getByText("常见流程的快速入口。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /系统指标/ }));
    expect(screen.getByText("分支数")).toBeInTheDocument();
  });

  it("test_simulation_summary_rail_updates_labels_when_language_changes", async () => {
    const { rerender } = renderSimulationSummaryRail();
    expect(screen.getByRole("heading", { name: "Simulation Snapshot" })).toBeInTheDocument();
    expect(screen.getByText("Status summary")).toBeInTheDocument();

    await switchLanguage("zh");
    rerender(<SimulationSummaryRail onHide={vi.fn()} onOpenLogs={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "模拟快照" })).toBeInTheDocument();
    expect(screen.getByText("状态摘要")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Simulation Snapshot" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /操作/ }));
    expect(screen.getByText("保存为模板")).toBeInTheDocument();
    expect(screen.getByText("打开研究日志")).toBeInTheDocument();
  });
});
