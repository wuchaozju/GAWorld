import React from "react";
import { Eye, GitBranchPlus, Network, Play, Settings2, Sparkles, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SimTree } from "../SimTree";
import { useSimulationStore } from "../../store";
import { buildWorkspacePath, getWorkspaceNodeLabel } from "./workspaceLabels";

interface TopologyStructureModalProps {
  isOpen: boolean;
  onClose: () => void;
  onOpenNodeDetails: () => void;
}

export const TopologyStructureModal: React.FC<TopologyStructureModalProps> = ({
  isOpen,
  onClose,
  onOpenNodeDetails,
}) => {
  const { t } = useTranslation();
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const nodes = useSimulationStore((state) => state.nodes);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const compareTargetNodeId = useSimulationStore((state) => state.compareTargetNodeId);
  const isCompareMode = useSimulationStore((state) => state.isCompareMode);
  const isGenerating = useSimulationStore((state) => state.isGenerating);
  const advanceSimulation = useSimulationStore((state) => state.advanceSimulation);
  const branchSimulation = useSimulationStore((state) => state.branchSimulation);
  const toggleCompareMode = useSimulationStore((state) => state.toggleCompareMode);
  const setCompareTarget = useSimulationStore((state) => state.setCompareTarget);
  const toggleExperimentDesigner = useSimulationStore((state) => state.toggleExperimentDesigner);
  const toggleNetworkEditor = useSimulationStore((state) => state.toggleNetworkEditor);

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

  if (!isOpen) return null;

  return (
    <div className="ss-topology-modal" role="dialog" aria-modal="true" aria-labelledby="ss-topology-modal-title">
      <div className="ss-topology-modal__backdrop" onClick={onClose} />

      <section className="ss-topology-modal__panel">
        <header className="ss-topology-modal__header">
          <div>
            <div className="ss-kicker">{t("components.workspace.topologyModal.kicker")}</div>
            <h2 id="ss-topology-modal-title">
              {currentSimulation?.name || t("components.workspace.topologyModal.title")}
            </h2>
            <p>{t("components.workspace.topologyModal.subtitle")}</p>
          </div>

          <button
            type="button"
            className="ss-icon-button"
            onClick={onClose}
            aria-label={t("components.workspace.topologyModal.closeAriaLabel")}
          >
            <X size={16} />
          </button>
        </header>

        <div className="ss-topology-modal__body">
          <div className="ss-topology-modal__tree-shell">
            <SimTree alwaysSelectOnClick />
          </div>

          <aside className="ss-topology-modal__side">
            <div className="ss-topology-modal__summary">
              <span>{t("components.workspace.topologyModal.currentPath")}</span>
              <strong>
                {currentPath.length
                  ? currentPath.map((node) => getWorkspaceNodeLabel(node, t)).join(" / ")
                  : t("components.workspace.topologyModal.emptyPath")}
              </strong>
            </div>

            <div className="ss-topology-modal__summary-grid">
              <div className="ss-topology-modal__summary-card">
                <span>{t("components.workspace.topologyModal.currentNode")}</span>
                <strong>{getWorkspaceNodeLabel(selectedNode, t)}</strong>
              </div>
              <div className="ss-topology-modal__summary-card">
                <span>{t("components.workspace.topologyModal.branches")}</span>
                <strong>{Math.max(nodes.length - 1, 0)}</strong>
              </div>
              <div className="ss-topology-modal__summary-card">
                <span>{t("components.workspace.topologyModal.nodesCount")}</span>
                <strong>{nodes.length}</strong>
              </div>
              <div className="ss-topology-modal__summary-card">
                <span>{t("components.workspace.topologyModal.compareStatus")}</span>
                <strong>{isCompareMode && compareTargetNodeId ? t("components.workspace.topologyModal.compareActive") : t("components.workspace.topologyModal.compareOff")}</strong>
              </div>
            </div>

            <div className="ss-topology-modal__action-group">
              <button
                type="button"
                className="ss-topology-modal__primary"
                onClick={() => void advanceSimulation()}
                disabled={!selectedNodeId || isGenerating}
              >
                <Play size={16} />
                <span>
                  {isGenerating
                    ? t("components.workspace.topologyModal.advancingNode")
                    : t("components.workspace.topologyModal.continueNode")}
                </span>
              </button>
              <button type="button" className="ss-summary-rail__action" onClick={onOpenNodeDetails}>
                <Eye size={15} />
                <span>{t("components.workspace.topologyModal.openNodeDetails")}</span>
              </button>
              <button
                type="button"
                className="ss-summary-rail__action"
                onClick={() => toggleExperimentDesigner(true)}
              >
                <Sparkles size={15} />
                <span>{t("components.workspace.topologyModal.experimentConfig")}</span>
              </button>
              <button
                type="button"
                className="ss-summary-rail__action"
                onClick={() => toggleNetworkEditor(true)}
              >
                <Network size={15} />
                <span>{t("components.workspace.topologyModal.networkConfig")}</span>
              </button>
              <button
                type="button"
                className="ss-summary-rail__action"
                onClick={() => void branchSimulation()}
                disabled={!selectedNodeId || isGenerating || isCompareMode}
              >
                <GitBranchPlus size={15} />
                <span>{t("components.workspace.topologyModal.branchFromNode")}</span>
              </button>
              <button
                type="button"
                className="ss-summary-rail__action"
                onClick={() => {
                  if (isCompareMode) {
                    toggleCompareMode(false);
                    setCompareTarget(null);
                    return;
                  }
                  toggleCompareMode(true);
                }}
              >
                <Settings2 size={15} />
                <span>{isCompareMode ? t("components.workspace.topologyModal.exitCompare") : t("components.workspace.topologyModal.enterCompare")}</span>
              </button>
            </div>
          </aside>
        </div>
      </section>
    </div>
  );
};

export default TopologyStructureModal;
