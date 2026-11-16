/**
 * Global experiment view shell for workspace.
 *
 * Wraps the main content area with a header showing branch comparison
 * or event/content view depending on compare mode state.
 *
 * Exports: GlobalExperimentView (default)
 */
import React from "react";
import { Activity, GitCompareArrows, GitCommit } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useSimulationStore } from "../../store";

interface GlobalExperimentViewProps {
  isCompareMode: boolean;
  children: React.ReactNode;
}

export const GlobalExperimentView: React.FC<GlobalExperimentViewProps> = ({
  isCompareMode,
  children,
}) => {
  const { t } = useTranslation();
  const logs = useSimulationStore((state) => state.logs);
  const rawEvents = useSimulationStore((state) => state.rawEvents);
  const nodes = useSimulationStore((state) => state.nodes);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);

  const selectedNode = React.useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) || nodes[0] || null,
    [nodes, selectedNodeId],
  );

  return (
    <section className="ss-global-view-shell" id="workspace-global">
      <div className="ss-global-view-shell__header">
        <div>
          <div className="ss-kicker">
            {isCompareMode ? t("components.workspace.globalExperiment.branchComparison") : t("controlRoom.globalStageTitle")}
          </div>
          <h2>
            {isCompareMode
              ? t("components.workspace.globalExperiment.branchComparison")
              : t("components.workspace.globalExperiment.eventsAndContent")}
          </h2>
        </div>

        <div className="ss-global-view-shell__stats">
          <div className="ss-global-view-shell__stat">
            <GitCommit size={14} />
            <span>{selectedNode?.display_id || selectedNode?.id || "—"}</span>
          </div>
          <div className="ss-global-view-shell__stat">
            <Activity size={14} />
            <span>{logs.length}</span>
          </div>
          <div className="ss-global-view-shell__stat">
            <GitCompareArrows size={14} />
            <span>{rawEvents.length}</span>
          </div>
        </div>
      </div>

      <div className="ss-global-view-shell__body">{children}</div>
    </section>
  );
};

export default GlobalExperimentView;
