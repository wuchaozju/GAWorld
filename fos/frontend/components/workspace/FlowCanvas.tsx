/**
 * Flow canvas component for workspace view.
 *
 * Renders the simulation flow as a vertical timeline with branch visualization,
 * showing node status, type labels, and branch navigation.
 *
 * Exports: FlowCanvas (default)
 */
import React from "react";
import { GitBranchPlus, Lock, Radio, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { useSimulationStore } from "../../store";
import type { SimNode } from "../../types";
import { buildWorkspacePath, getWorkspaceNodeLabel } from "./workspaceLabels";

interface FlowCanvasProps {
  onOpenDetails: () => void;
  onOpenTopology: () => void;
}

const compareNodes = (left: SimNode, right: SimNode) =>
  String(left.display_id || left.id).localeCompare(String(right.display_id || right.id), undefined, {
    numeric: true,
    sensitivity: "base",
  });

const summarizeNode = (
  node: SimNode,
  latestContent: string | null,
  t: TFunction,
) => {
  if (latestContent) {
    return latestContent.replace(/\s+/g, " ").trim().slice(0, 120);
  }
  if (node.depth === 0) {
    return t("components.workspace.flowCanvas.startNodeDesc");
  }
  if (node.status === "pending") {
    return t("components.workspace.flowCanvas.lockedNodeDesc");
  }
  if (node.status === "running") {
    return t("components.workspace.flowCanvas.simulatingNodeDesc");
  }
  if (node.status === "failed") {
    return t("components.workspace.flowCanvas.interruptedNodeDesc");
  }
  return t("components.workspace.flowCanvas.completedNodeDesc");
};

const getNodeTypeLabel = (
  node: SimNode,
  childCount: number,
  t: TFunction,
) => {
  if (node.depth === 0) return t("components.workspace.flowCanvas.startLabel");
  if (childCount > 1) return t("components.workspace.flowCanvas.branchLabel");
  if (node.isLeaf && node.status === "completed") return t("components.workspace.flowCanvas.outcomeLabel");
  return t("components.workspace.flowCanvas.decisionLabel");
};

export const FlowCanvas: React.FC<FlowCanvasProps> = ({ onOpenDetails, onOpenTopology }) => {
  const { t } = useTranslation();
  const nodes = useSimulationStore((state) => state.nodes);
  const logs = useSimulationStore((state) => state.logs);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const compareTargetNodeId = useSimulationStore((state) => state.compareTargetNodeId);
  const isCompareMode = useSimulationStore((state) => state.isCompareMode);
  const selectNode = useSimulationStore((state) => state.selectNode);
  const setCompareTarget = useSimulationStore((state) => state.setCompareTarget);

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

  const childMap = React.useMemo(() => {
    const map = new Map<string | null, SimNode[]>();
    nodes.forEach((node) => {
      const key = node.parentId;
      const current = map.get(key) || [];
      current.push(node);
      current.sort(compareNodes);
      map.set(key, current);
    });
    return map;
  }, [nodes]);

  const latestByNode = React.useMemo(() => {
    const map = new Map<string, string>();
    for (let index = logs.length - 1; index >= 0; index -= 1) {
      const entry = logs[index];
      if (!map.has(entry.nodeId)) {
        map.set(entry.nodeId, entry.content);
      }
    }
    return map;
  }, [logs]);

  const selectedSiblings = React.useMemo(() => {
    if (!selectedNode) return [];
    return (childMap.get(selectedNode.parentId) || [])
      .filter((node) => node.id !== selectedNode.id)
      .sort(compareNodes);
  }, [childMap, selectedNode]);

  const selectedChildren = React.useMemo(
    () => (selectedNode ? (childMap.get(selectedNode.id) || []).sort(compareNodes) : []),
    [childMap, selectedNode],
  );

  const handleActivateNode = (nodeId: string) => {
    if (isCompareMode && nodeId !== selectedNodeId) {
      setCompareTarget(nodeId);
      return;
    }
    selectNode(nodeId);
  };

  return (
    <section className="ss-flow-canvas" id="workspace-flow">
      <div className="ss-flow-canvas__header">
        <div>
          <div className="ss-kicker">{t("components.workspace.flowCanvas.title")}</div>
          <h2>{t("components.workspace.flowCanvas.subtitle")}</h2>
          <p>
            {t("components.workspace.flowCanvas.description")}
          </p>
        </div>

        <div className="ss-flow-canvas__stats">
          <span className="ss-flow-canvas__stat">
            <Radio size={14} />
            {t("components.workspace.flowCanvas.nodeCount", { count: nodes.length })}
          </span>
          <span className="ss-flow-canvas__stat">
            <GitBranchPlus size={14} />
            {t("components.workspace.flowCanvas.branchCount", { count: Math.max(nodes.length - 1, 0) })}
          </span>
          <button type="button" className="ss-flow-canvas__stat is-action" onClick={onOpenDetails}>
            <Sparkles size={14} />
            {t("components.workspace.flowCanvas.openNodeDetails")}
          </button>
          <button type="button" className="ss-flow-canvas__stat is-action" onClick={onOpenTopology}>
            <GitBranchPlus size={14} />
            {t("components.workspace.flowCanvas.openTopology")}
          </button>
        </div>
      </div>

      <div className="ss-flow-canvas__track">
        {currentPath.map((node, index) => {
          const nextPathNode = currentPath[index + 1] || null;
          const alternatives = (childMap.get(node.id) || []).filter((child) => child.id !== nextPathNode?.id);
          const childCount = (childMap.get(node.id) || []).length;
          const nodeType = getNodeTypeLabel(node, childCount, t);
          const summary = summarizeNode(node, latestByNode.get(node.id) || null, t);
          const isCurrent = node.id === selectedNodeId;
          const isCompare = compareTargetNodeId === node.id;

          return (
            <div key={node.id} className="ss-flow-canvas__step">
              <div className="ss-flow-canvas__rail">
                <span className={`ss-flow-canvas__dot${isCurrent ? " is-current" : ""}${isCompare ? " is-compare" : ""}`}>
                  {node.status === "pending" ? <Lock size={14} /> : <span />}
                </span>
                {index < currentPath.length - 1 ? <span className="ss-flow-canvas__line" /> : null}
              </div>

              <div className="ss-flow-canvas__step-main">
                <button
                  type="button"
                  onClick={() => handleActivateNode(node.id)}
                  className={`ss-flow-node${isCurrent ? " is-current" : ""}${node.status === "pending" ? " is-locked" : ""}${isCompare ? " is-compare" : ""}`}
                >
                  <div className="ss-flow-node__top">
                    <div>
                      <span className="ss-flow-node__type">{nodeType}</span>
                      <h3>{getWorkspaceNodeLabel(node, t)}</h3>
                    </div>
                    <div className="ss-flow-node__badges">
                      <span className={`ss-flow-node__status is-${node.status}`}>
                        {isCurrent ? t("components.workspace.flowCanvas.current") : t(`topologyExplorer.status.${node.status}`)}
                      </span>
                      <span className="ss-flow-node__display-id">{node.display_id || node.id}</span>
                    </div>
                  </div>
                  <p>{summary}</p>
                </button>

                {alternatives.length ? (
                  <div className="ss-flow-canvas__branch-strip">
                    <span className="ss-flow-canvas__branch-label">{t("components.workspace.flowCanvas.availableBranches")}</span>
                    <div className="ss-flow-canvas__branch-grid">
                      {alternatives.map((branch) => (
                        <button
                          key={branch.id}
                          type="button"
                          onClick={() => handleActivateNode(branch.id)}
                          className={`ss-flow-branch${compareTargetNodeId === branch.id ? " is-compare" : ""}${branch.status === "pending" ? " is-pending" : ""}`}
                        >
                          <strong>{getWorkspaceNodeLabel(branch, t)}</strong>
                          <span>{summarizeNode(branch, latestByNode.get(branch.id) || null, t)}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      {selectedSiblings.length || selectedChildren.length ? (
        <div className="ss-flow-canvas__nearby">
          {selectedSiblings.length ? (
            <div className="ss-flow-canvas__nearby-block">
              <span>{t("components.workspace.flowCanvas.siblingBranches")}</span>
              <div className="ss-flow-canvas__branch-grid">
                {selectedSiblings.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => handleActivateNode(node.id)}
                    className={`ss-flow-branch${compareTargetNodeId === node.id ? " is-compare" : ""}${node.status === "pending" ? " is-pending" : ""}`}
                  >
                    <strong>{getWorkspaceNodeLabel(node, t)}</strong>
                    <span>{summarizeNode(node, latestByNode.get(node.id) || null, t)}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {selectedChildren.length ? (
            <div className="ss-flow-canvas__nearby-block">
              <span>{t("components.workspace.flowCanvas.nextLayer")}</span>
              <div className="ss-flow-canvas__branch-grid">
                {selectedChildren.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => handleActivateNode(node.id)}
                    className={`ss-flow-branch${compareTargetNodeId === node.id ? " is-compare" : ""}${node.status === "pending" ? " is-pending" : ""}`}
                  >
                    <strong>{getWorkspaceNodeLabel(node, t)}</strong>
                    <span>{summarizeNode(node, latestByNode.get(node.id) || null, t)}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
};

export default FlowCanvas;
