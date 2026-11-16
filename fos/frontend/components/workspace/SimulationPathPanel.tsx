import React from "react";
import { ArrowUpLeft, ChevronRight, GitCompareArrows, GitFork, Layers3, Rows3 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { useSimulationStore } from "../../store";
import { buildBranchContextHref } from "../../utils/branchContext";
import { buildWorkspacePath, getWorkspaceNodeLabel } from "./workspaceLabels";

interface SimulationPathPanelProps {
  detailsOpen: boolean;
  onToggleDetails: () => void;
  onRequestCreateBranch: () => void;
}

export const SimulationPathPanel: React.FC<SimulationPathPanelProps> = ({
  detailsOpen,
  onToggleDetails,
  onRequestCreateBranch,
}) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const nodes = useSimulationStore((state) => state.nodes);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const compareTargetNodeId = useSimulationStore((state) => state.compareTargetNodeId);
  const isCompareMode = useSimulationStore((state) => state.isCompareMode);
  const selectNode = useSimulationStore((state) => state.selectNode);
  const setCompareTarget = useSimulationStore((state) => state.setCompareTarget);
  const toggleCompareMode = useSimulationStore((state) => state.toggleCompareMode);

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

  const handleToggleCompare = () => {
    if (isCompareMode) {
      toggleCompareMode(false);
      setCompareTarget(null);
      return;
    }
    toggleCompareMode(true);
  };

  const handleActivateNode = (nodeId: string) => {
    if (isCompareMode && nodeId !== selectedNodeId) {
      setCompareTarget(nodeId);
      return;
    }
    selectNode(nodeId);
  };

  const handleOpenTopology = () => {
    if (!currentSimulation?.id) return;
    navigate(
      buildBranchContextHref(
        `/simulations/${currentSimulation.id}/topology`,
        selectedNodeId,
        isCompareMode ? compareTargetNodeId : null,
      ),
    );
  };

  return (
    <section className="ss-path-strip">
      <div className="ss-path-strip__copy">
        <div className="ss-kicker">{t("controlRoom.pathManagerTitle")}</div>
        <h2>{t("components.workspace.simulationPath.title")}</h2>
        <p>{t("components.workspace.simulationPath.subtitle")}</p>
      </div>

      <div className="ss-path-strip__trail" role="navigation" aria-label={t("controlRoom.currentPath")}>
        {currentPath.map((node, index) => (
          <React.Fragment key={node.id}>
            <button
              type="button"
              onClick={() => handleActivateNode(node.id)}
              className={`ss-path-strip__crumb${node.id === selectedNodeId ? " is-selected" : ""}${
                node.id === compareTargetNodeId ? " is-compare" : ""
              }`}
            >
              <strong>{getWorkspaceNodeLabel(node, t)}</strong>
              <span>{node.display_id || node.id}</span>
            </button>
            {index < currentPath.length - 1 ? (
              <ChevronRight size={14} className="ss-path-strip__separator" aria-hidden />
            ) : null}
          </React.Fragment>
        ))}
      </div>

      <div className="ss-path-strip__actions">
        <button
          type="button"
          onClick={() => parentNode && handleActivateNode(parentNode.id)}
          disabled={!parentNode}
          className="ss-button-secondary"
        >
          <ArrowUpLeft size={15} />
          {t("controlRoom.returnToParentBranch")}
        </button>
        <button
          type="button"
          onClick={onRequestCreateBranch}
          className="ss-button-secondary"
        >
          <GitFork size={15} />
          {t("controlRoom.createBranchPrimary")}
        </button>
        <button type="button" onClick={handleToggleCompare} className="ss-button-secondary">
          <GitCompareArrows size={15} />
          {isCompareMode ? t("simulationWorkspace.compareExit") : t("simulationWorkspace.compare")}
        </button>
        <button
          type="button"
          onClick={onToggleDetails}
          className={`ss-button-secondary${detailsOpen ? " is-active" : ""}`}
        >
          <Rows3 size={15} />
          {detailsOpen ? t("controlRoom.hideBranchDetails") : t("controlRoom.showBranchDetails")}
        </button>
        <button type="button" onClick={handleOpenTopology} className="ss-button-secondary">
          <Layers3 size={15} />
          {t("controlRoom.openFullBranchMap")}
        </button>
      </div>
    </section>
  );
};

export default SimulationPathPanel;
