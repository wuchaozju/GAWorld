import React from "react";
import { useTranslation } from "react-i18next";
import { GitFork, Info, X } from "lucide-react";

import { useSimulationStore } from "../../store";
import type { SimNode } from "../../types";

const GENERIC_NODE_PATTERN = /^(Node \d+|节点 \d+)$/;

const getNodeLabel = (node: SimNode | null, t: (key: string, options?: any) => string) => {
  if (!node) return "—";
  if (node.depth === 0) return "起始";
  if (node.name && !GENERIC_NODE_PATTERN.test(node.name)) return node.name;
  return t("controlRoom.roundNodeLabel", { round: node.depth });
};

interface BranchComposerDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

export const BranchComposerDialog: React.FC<BranchComposerDialogProps> = ({
  isOpen,
  onClose,
}) => {
  const { t } = useTranslation();
  const nodes = useSimulationStore((state) => state.nodes);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const branchSimulation = useSimulationStore((state) => state.branchSimulation);
  const isGenerating = useSimulationStore((state) => state.isGenerating);

  const selectedNode = React.useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) || nodes[0] || null,
    [nodes, selectedNodeId],
  );

  const selectedLabel = getNodeLabel(selectedNode, t);

  const handleCreateBranch = async () => {
    if (!selectedNode) return;
    await branchSimulation();
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="ss-path__composer-backdrop" onClick={onClose}>
      <div className="ss-path__composer" onClick={(event) => event.stopPropagation()}>
        <div className="ss-path__composer-header">
          <div>
            <div className="ss-kicker">{t("controlRoom.createBranchDialogKicker")}</div>
            <h3>{t("controlRoom.createBranchDialogTitle")}</h3>
            <p>{t("controlRoom.createBranchDialogCopy")}</p>
          </div>
          <button onClick={onClose} className="ss-icon-button square" title={t("common.close")}>
            <X size={16} />
          </button>
        </div>

        <div className="ss-path__composer-body">
          <div className="ss-path__composer-field">
            <label>{t("controlRoom.sourceNode")}</label>
            <div className="ss-path__composer-readonly">
              <strong>{selectedLabel}</strong>
              <span>{selectedNode?.display_id || "—"}</span>
            </div>
          </div>

          <div className="ss-path__composer-field">
            <label>{t("controlRoom.branchType")}</label>
            <div className="ss-path__composer-readonly">
              <strong>{t("controlRoom.branchTypeParallel")}</strong>
              <span>{t("controlRoom.branchSafeHint")}</span>
            </div>
          </div>

          <div className="ss-path__composer-field">
            <label>{t("controlRoom.inheritCurrentState")}</label>
            <div className="ss-path__composer-readonly ss-path__composer-readonly--toggle">
              <input type="checkbox" checked readOnly />
              <div>
                <strong>{t("controlRoom.inheritCurrentStateEnabled")}</strong>
                <span>{t("controlRoom.inheritCurrentStateFixed")}</span>
              </div>
            </div>
          </div>

          <div className="ss-path__composer-help">
            <Info size={15} />
            <span>
              {t("controlRoom.branchSafeHint")}
              {" "}
              {t("controlRoom.createAndRun")}
            </span>
          </div>
          <div className="ss-path__composer-help">
            <Info size={15} />
            <span>
              {t("controlRoom.createBranchDialogCopy")}
            </span>
          </div>
        </div>

        <div className="ss-path__composer-actions">
          <button onClick={onClose} className="ss-button-secondary">
            {t("common.cancel")}
          </button>
          <button
            onClick={() => void handleCreateBranch()}
            disabled={isGenerating}
            className="ss-button"
          >
            <GitFork size={15} />
            {t("controlRoom.createAndRun")}
          </button>
        </div>
      </div>
    </div>
  );
};

export default BranchComposerDialog;
