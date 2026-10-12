import React from "react";
import { BookOpenText, FileCode2, GitBranchPlus, ScrollText } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ComparisonView } from "../ComparisonView";
import { LogViewer } from "../LogViewer";
import { useSimulationStore } from "../../store";
import { resolveAgentDisplayName } from "../../store/helpers";
import { buildWorkspacePath, getWorkspaceNodeLabel } from "./workspaceLabels";

export type NodeDetailTab = "events" | "branches" | "logs" | "raw";

interface NodeDetailPanelProps {
  activeTab: NodeDetailTab;
  onChangeTab: (tab: NodeDetailTab) => void;
  selectedAgentId: string | null;
  onClearSelectedAgent: () => void;
}

const DETAIL_TABS = [
  { id: "events", icon: ScrollText },
  { id: "branches", icon: GitBranchPlus },
  { id: "logs", icon: BookOpenText },
  { id: "raw", icon: FileCode2 },
] as const;

export const NodeDetailPanel: React.FC<NodeDetailPanelProps> = ({
  activeTab,
  onChangeTab,
  selectedAgentId,
  onClearSelectedAgent,
}) => {
  const { t } = useTranslation();
  const nodes = useSimulationStore((state) => state.nodes);
  const logs = useSimulationStore((state) => state.logs);
  const rawEvents = useSimulationStore((state) => state.rawEvents);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const compareTargetNodeId = useSimulationStore((state) => state.compareTargetNodeId);
  const isCompareMode = useSimulationStore((state) => state.isCompareMode);
  const isGenerating = useSimulationStore((state) => state.isGenerating);
  const selectNode = useSimulationStore((state) => state.selectNode);
  const setCompareTarget = useSimulationStore((state) => state.setCompareTarget);
  const agents = useSimulationStore((state) => state.agents);

  const selectedNode = React.useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) || nodes[0] || null,
    [nodes, selectedNodeId],
  );

  const nodeLookup = React.useMemo(
    () => new Map(nodes.map((node) => [node.id, node])),
    [nodes],
  );

  const currentPath = React.useMemo(
    () => buildWorkspacePath(selectedNode, nodeLookup),
    [nodeLookup, selectedNode],
  );

  const parentNode = selectedNode?.parentId ? nodeLookup.get(selectedNode.parentId) || null : null;
  const siblingNodes = React.useMemo(
    () =>
      selectedNode
        ? nodes.filter((node) => node.parentId === selectedNode.parentId && node.id !== selectedNode.id)
        : [],
    [nodes, selectedNode],
  );
  const childNodes = React.useMemo(
    () => (selectedNode ? nodes.filter((node) => node.parentId === selectedNode.id) : []),
    [nodes, selectedNode],
  );
  const selectedNodeLogs = React.useMemo(
    () => logs.filter((entry) => entry.nodeId === selectedNodeId).slice().reverse(),
    [logs, selectedNodeId],
  );

  const selectedNodeRawEvents = React.useMemo(() => {
    return rawEvents.filter((event: any) => String(event?.node_id ?? event?.nodeId ?? selectedNodeId) === selectedNodeId);
  }, [rawEvents, selectedNodeId]);

  const tabLabel = React.useCallback(
    (tab: NodeDetailTab) => {
      if (tab === "events") return t("components.workspace.nodeDetail.eventsTab");
      if (tab === "branches") return t("components.workspace.nodeDetail.branchesTab");
      if (tab === "logs") return t("components.workspace.nodeDetail.logsTab");
      return t("components.workspace.nodeDetail.rawTab");
    },
    [t],
  );

  const handleActivateNode = (nodeId: string) => {
    if (isCompareMode && nodeId !== selectedNodeId) {
      setCompareTarget(nodeId);
      return;
    }
    selectNode(nodeId);
  };

  const runStatus = isGenerating
    ? t("simulationWorkspace.running")
    : t(`topologyExplorer.status.${selectedNode?.status || "pending"}`);
  const roundLabel = selectedNode?.depth != null && selectedNode.depth > 0
    ? t("components.workspace.nodeDetail.roundN", { n: selectedNode.depth })
    : t("components.workspace.nodeDetail.start");

  return (
    <section className="ss-node-detail" id="workspace-detail">
      <div className="ss-node-detail__header">
        <div className="ss-node-detail__tabs">
          {DETAIL_TABS.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => onChangeTab(tab.id)}
                className={`ss-node-detail__tab${activeTab === tab.id ? " is-active" : ""}`}
              >
                <Icon size={14} />
                <span>{tabLabel(tab.id)}</span>
              </button>
            );
          })}
        </div>

        <div className="ss-node-detail__meta-strip">
          <div className="ss-node-detail__meta-item">
            <span>{t("components.workspace.nodeDetail.round")}</span>
            <strong>{roundLabel}</strong>
          </div>
          <div className="ss-node-detail__meta-item">
            <span>{t("components.workspace.nodeDetail.status")}</span>
            <strong>{runStatus}</strong>
          </div>
          <div className="ss-node-detail__meta-item">
            <span>{t("components.workspace.nodeDetail.node")}</span>
            <strong>{getWorkspaceNodeLabel(selectedNode, t)}</strong>
          </div>
        </div>
      </div>

      <div className={`ss-node-detail__body${activeTab === "events" ? " is-events" : " is-scrollable"}`}>
        {activeTab === "events" ? (
          <div className="ss-node-detail__viewer">
            {isCompareMode ? (
              <ComparisonView />
            ) : (
              <LogViewer />
            )}
          </div>
        ) : null}

        {activeTab === "branches" ? (
          <div className="ss-node-detail__grid">
            <div className="ss-node-detail__card">
              <span>{t("components.workspace.nodeDetail.currentPath")}</span>
              <strong>
                {currentPath.length
                  ? currentPath.map((node) => getWorkspaceNodeLabel(node, t)).join(" / ")
                  : "—"}
              </strong>
            </div>
            <div className="ss-node-detail__card">
              <span>{t("components.workspace.nodeDetail.parentBranch")}</span>
              <strong>{parentNode ? getWorkspaceNodeLabel(parentNode, t) : t("components.workspace.nodeDetail.noParentBranch")}</strong>
            </div>
            <div className="ss-node-detail__card">
              <span>{t("components.workspace.nodeDetail.siblingBranches")}</span>
              <strong>{String(siblingNodes.length)}</strong>
            </div>
            <div className="ss-node-detail__card">
              <span>{t("components.workspace.nodeDetail.childNodes")}</span>
              <strong>{String(childNodes.length)}</strong>
            </div>

            <div className="ss-node-detail__list-card">
              <span>{t("components.workspace.nodeDetail.switchableBranches")}</span>
              {siblingNodes.length ? (
                siblingNodes.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => handleActivateNode(node.id)}
                    className={`ss-node-detail__list-item${compareTargetNodeId === node.id ? " is-compare" : ""}`}
                  >
                    <strong>{getWorkspaceNodeLabel(node, t)}</strong>
                    <span>{node.display_id || node.id}</span>
                  </button>
                ))
              ) : (
                <div className="ss-node-detail__empty">{t("components.workspace.nodeDetail.noSiblings")}</div>
              )}
            </div>

            <div className="ss-node-detail__list-card">
              <span>{t("components.workspace.nodeDetail.childPaths")}</span>
              {childNodes.length ? (
                childNodes.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => handleActivateNode(node.id)}
                    className={`ss-node-detail__list-item${compareTargetNodeId === node.id ? " is-compare" : ""}`}
                  >
                    <strong>{getWorkspaceNodeLabel(node, t)}</strong>
                    <span>{node.display_id || node.id}</span>
                  </button>
                ))
              ) : (
                <div className="ss-node-detail__empty">{t("components.workspace.nodeDetail.noChildren")}</div>
              )}
            </div>
          </div>
        ) : null}

        {activeTab === "logs" ? (
          <div className="ss-node-detail__list-card is-tall">
            <span>{t("components.workspace.nodeDetail.researchLogs")}</span>
            {selectedNodeLogs.length ? (
              selectedNodeLogs.map((entry) => (
                <div key={entry.id} className="ss-node-detail__log-item">
                  <div className="ss-node-detail__log-top">
                    <strong>{entry.agentId ? resolveAgentDisplayName(entry.agentId, agents) : t("components.workspace.nodeDetail.systemLabel")}</strong>
                    <span>{entry.timestamp}</span>
                  </div>
                  <p>{entry.content}</p>
                </div>
              ))
            ) : (
              <div className="ss-node-detail__empty">
                {t("components.workspace.nodeDetail.noLogs")}
              </div>
            )}
          </div>
        ) : null}

        {activeTab === "raw" ? (
          <div className="ss-node-detail__raw-card">
            <span>{t("components.workspace.nodeDetail.rawEventData")}</span>
            {selectedNodeRawEvents.length ? (
              <pre>{JSON.stringify(selectedNodeRawEvents, null, 2)}</pre>
            ) : (
              <div className="ss-node-detail__empty">
                {t("components.workspace.nodeDetail.noRawData")}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
};

export default NodeDetailPanel;
