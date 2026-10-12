/**
 * This file tests TopologyStructureModal language behavior while it renders.
 * renderTopologyStructureModal renders the modal with simple store data.
 * test_topology_structure_modal_shows_english_labels_by_default checks default English labels.
 * test_topology_structure_modal_shows_chinese_labels_after_language_switch checks labels after switching to Chinese.
 * test_topology_structure_modal_updates_labels_when_language_changes checks labels update after language change and rerender.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TopologyStructureModal } from "../workspace/TopologyStructureModal";
import { resetLanguage, switchLanguage } from "../../test-utils/i18n";

type Language = "en" | "zh";

interface NodeShape {
  id: string;
  display_id: string;
  name: string;
  parentId: string | null;
}

interface StoreState {
  currentSimulation: { name: string } | null;
  nodes: NodeShape[];
  selectedNodeId: string | null;
  compareTargetNodeId: string | null;
  isCompareMode: boolean;
  isGenerating: boolean;
  advanceSimulation: () => Promise<void>;
  branchSimulation: () => Promise<void>;
  toggleCompareMode: (value: boolean) => void;
  setCompareTarget: (value: string | null) => void;
  toggleExperimentDesigner: (value: boolean) => void;
  toggleNetworkEditor: (value: boolean) => void;
}

let mockState: StoreState;

vi.mock("../SimTree", () => ({
  SimTree: () => <div>Mocked SimTree</div>,
}));

vi.mock("../../store", () => ({
  useSimulationStore: (selector: (state: StoreState) => unknown) => selector(mockState),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => {
    const language = (globalThis as unknown as { i18n: { language: Language } }).i18n.language;
    const translations: Record<Language, Record<string, string>> = {
      en: {
        "components.workspace.topologyModal.kicker": "Full topology",
        "components.workspace.topologyModal.subtitle":
          "Review the full node topology here and jump directly into experiment or network configuration.",
        "components.workspace.topologyModal.closeAriaLabel": "Close topology",
        "components.workspace.topologyModal.emptyPath": "—",
        "components.workspace.topologyModal.currentPath": "Current path",
        "components.workspace.topologyModal.currentNode": "Current node",
        "components.workspace.topologyModal.branches": "Branches",
        "components.workspace.topologyModal.nodesCount": "Nodes",
        "components.workspace.topologyModal.compareStatus": "Compare status",
        "components.workspace.topologyModal.compareOff": "Compare off",
        "components.workspace.topologyModal.compareActive": "Compare active",
        "components.workspace.topologyModal.continueNode": "Continue node",
        "components.workspace.topologyModal.openNodeDetails": "Open node details",
      },
      zh: {
        "components.workspace.topologyModal.kicker": "完整拓扑结构",
        "components.workspace.topologyModal.subtitle": "在完整拓扑视图中查看全部节点与分支，并直接打开实验配置与网络配置。",
        "components.workspace.topologyModal.closeAriaLabel": "关闭拓扑结构",
        "components.workspace.topologyModal.emptyPath": "—",
        "components.workspace.topologyModal.currentPath": "当前路径",
        "components.workspace.topologyModal.currentNode": "当前节点",
        "components.workspace.topologyModal.branches": "分支",
        "components.workspace.topologyModal.nodesCount": "节点数",
        "components.workspace.topologyModal.compareStatus": "对比状态",
        "components.workspace.topologyModal.compareOff": "未开启对比",
        "components.workspace.topologyModal.compareActive": "对比中",
        "components.workspace.topologyModal.continueNode": "继续节点",
        "components.workspace.topologyModal.openNodeDetails": "打开节点详情",
      },
    };
    return {
      t: (key: string) => translations[language][key] ?? key,
      i18n: (globalThis as unknown as { i18n: { language: Language } }).i18n,
    };
  },
}));

function renderTopologyStructureModal(): ReturnType<typeof render> {
  return render(
    <TopologyStructureModal
      isOpen
      onClose={vi.fn()}
      onOpenNodeDetails={vi.fn()}
    />,
  );
}

describe("TopologyStructureModal i18n", () => {
  beforeEach(async () => {
    await resetLanguage();
    mockState = {
      currentSimulation: { name: "Demo Simulation" },
      nodes: [
        { id: "node-1", display_id: "node-1", name: "Root", parentId: null },
        { id: "node-2", display_id: "node-2", name: "Child", parentId: "node-1" },
      ],
      selectedNodeId: "node-2",
      compareTargetNodeId: null,
      isCompareMode: false,
      isGenerating: false,
      advanceSimulation: vi.fn(async () => {}),
      branchSimulation: vi.fn(async () => {}),
      toggleCompareMode: vi.fn(),
      setCompareTarget: vi.fn(),
      toggleExperimentDesigner: vi.fn(),
      toggleNetworkEditor: vi.fn(),
    };
  });

  afterEach(async () => {
    await resetLanguage();
  });

  it("test_topology_structure_modal_shows_english_labels_by_default", () => {
    renderTopologyStructureModal();
    expect(screen.getByText("Full topology")).toBeInTheDocument();
    expect(screen.getByText("Current path")).toBeInTheDocument();
    expect(screen.getByText("Current node")).toBeInTheDocument();
    expect(screen.getByText("Compare status")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close topology" })).toBeInTheDocument();
  });

  it("test_topology_structure_modal_shows_chinese_labels_after_language_switch", async () => {
    await switchLanguage("zh");
    renderTopologyStructureModal();
    expect(screen.getByText("完整拓扑结构")).toBeInTheDocument();
    expect(screen.getByText("当前路径")).toBeInTheDocument();
    expect(screen.getByText("当前节点")).toBeInTheDocument();
    expect(screen.getByText("对比状态")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭拓扑结构" })).toBeInTheDocument();
  });

  it("test_topology_structure_modal_updates_labels_when_language_changes", async () => {
    const { rerender } = renderTopologyStructureModal();
    expect(screen.getByText("Full topology")).toBeInTheDocument();
    expect(screen.getByText("Current path")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close topology" })).toBeInTheDocument();

    await switchLanguage("zh");
    rerender(
      <TopologyStructureModal
        isOpen
        onClose={vi.fn()}
        onOpenNodeDetails={vi.fn()}
      />,
    );

    expect(screen.getByText("完整拓扑结构")).toBeInTheDocument();
    expect(screen.getByText("当前路径")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭拓扑结构" })).toBeInTheDocument();
    expect(screen.queryByText("Full topology")).not.toBeInTheDocument();
  });
});
