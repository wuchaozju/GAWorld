import React from "react";
import { useTranslation } from "react-i18next";

import { useSimulationStore } from "../../store";
import { buildWorkspacePath, getWorkspaceNodeLabel } from "./workspaceLabels";

interface NodeHeroCardProps {
  observationMode: "global" | "focused" | "compare";
}

export const NodeHeroCard: React.FC<NodeHeroCardProps> = ({ observationMode }) => {
  const { t } = useTranslation();
  const nodes = useSimulationStore((state) => state.nodes);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const llmProviders = useSimulationStore((state) => state.llmProviders);
  const selectedProviderId = useSimulationStore((state) => state.selectedProviderId);
  const currentProviderId = useSimulationStore((state) => state.currentProviderId);
  const isCompareMode = useSimulationStore((state) => state.isCompareMode);

  const selectedNode = React.useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) || nodes[0] || null,
    [nodes, selectedNodeId],
  );

  const nodeLookup = React.useMemo(
    () => new Map(nodes.map((node) => [node.id, node])),
    [nodes],
  );

  const parentNode = selectedNode?.parentId ? nodeLookup.get(selectedNode.parentId) || null : null;
  const childCount = React.useMemo(
    () => nodes.filter((node) => node.parentId === selectedNode?.id).length,
    [nodes, selectedNode?.id],
  );
  const siblingCount = React.useMemo(
    () =>
      selectedNode
        ? nodes.filter((node) => node.parentId === selectedNode.parentId && node.id !== selectedNode.id).length
        : 0,
    [nodes, selectedNode],
  );

  const currentPath = React.useMemo(
    () => buildWorkspacePath(selectedNode, nodeLookup),
    [nodeLookup, selectedNode],
  );

  const sceneConfig = (currentSimulation?.scene_config ?? {}) as Record<string, any>;
  const scenarioSummary =
    sceneConfig.description ||
    sceneConfig.initial_event ||
    currentSimulation?.description ||
    t("simulationWorkspace.subtitleFallback");
  const providerSelection = selectedProviderId ?? currentProviderId ?? null;
  const selectedProvider =
    llmProviders.find((provider) => provider.id === providerSelection) || null;
  const observationLabel =
    observationMode === "compare"
      ? t("controlRoom.modeCompare")
      : observationMode === "focused"
        ? t("controlRoom.modeFocused")
        : t("controlRoom.modeGlobal");
  const nodeLabel = getWorkspaceNodeLabel(selectedNode, t);

  return (
    <section className="ss-node-hero" id="workspace-node">
      <div className="ss-node-hero__content">
        <div className="ss-node-hero__headline">
          <div className="ss-kicker">{t("components.workspace.nodeHero.overview")}</div>
          <div className="ss-node-hero__path">
            <span>{t("controlRoom.currentPath")}</span>
            <strong>
              {currentPath.length
                ? currentPath.map((node) => getWorkspaceNodeLabel(node, t)).join(" / ")
                : t("controlRoom.valueUnavailable")}
            </strong>
          </div>
          <h2 className="ss-node-hero__title">{nodeLabel}</h2>
          <p className="ss-node-hero__summary">{scenarioSummary}</p>
        </div>

        <div className="ss-node-hero__pills">
          <span className="ss-pill ss-pill--active">{t("controlRoom.statusCurrent")}</span>
          <span className="ss-pill ss-pill--quiet">
            {t(`topologyExplorer.status.${selectedNode?.status || "pending"}`)}
          </span>
          <span className="ss-pill ss-pill--quiet">{observationLabel}</span>
          {isCompareMode ? <span className="ss-pill ss-pill--quiet">{t("controlRoom.compareActive")}</span> : null}
          <span className="ss-pill ss-pill--quiet">{t("components.workspace.nodeHero.controlMode")}</span>
        </div>

        <div className="ss-node-hero__config">
          <div className="ss-node-hero__config-label">{t("controlRoom.currentNodeConfiguration")}</div>
          <strong>{currentSimulation?.name || t("simulationWorkspace.titleFallback")}</strong>
        </div>
      </div>

      <div className="ss-node-hero__meta">
        <div className="ss-node-hero__meta-card">
          <span>{t("controlRoom.nodeIdLabel")}</span>
          <strong>{selectedNode?.display_id || selectedNode?.id || t("controlRoom.valueUnavailable")}</strong>
        </div>
        <div className="ss-node-hero__meta-card">
          <span>{t("simulationWorkspace.metrics.worldTime")}</span>
          <strong>{selectedNode?.worldTime || t("controlRoom.valueUnavailable")}</strong>
        </div>
        <div className="ss-node-hero__meta-card">
          <span>{t("simulationWorkspace.provider")}</span>
          <strong>
            {selectedProvider
              ? `${selectedProvider.name || selectedProvider.provider}${selectedProvider.model ? ` · ${selectedProvider.model}` : ""}`
              : t("simulationWorkspace.noProvider")}
          </strong>
          <p>{t("simPage.fosEngine")}</p>
        </div>
        <div className="ss-node-hero__meta-card">
          <span>{t("controlRoom.branchRelations")}</span>
          <strong>
            {t("controlRoom.branchCountsInline", {
              parent: parentNode ? 1 : 0,
              siblings: siblingCount,
              children: childCount,
            })}
          </strong>
          <p>{t("controlRoom.branchRelationsHint")}</p>
        </div>
      </div>
    </section>
  );
};

export default NodeHeroCard;

