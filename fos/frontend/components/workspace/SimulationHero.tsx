import React from "react";
import { ArrowUpLeft, Eye, GitCompareArrows, GitFork, MoreHorizontal, Play } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useSimulationStore } from "../../store";
import { getWorkspaceNodeLabel } from "./workspaceLabels";

interface SimulationHeroProps {
  observationMode: "global" | "focused" | "compare";
  isGenerating: boolean;
  isCompareMode: boolean;
  canReturnToParent: boolean;
  onContinue: () => void;
  onCreateBranch: () => void;
  onViewDetails: () => void;
  onToggleCompare: () => void;
  onOpenNode: () => void;
  onReturnToParent: () => void;
}

const getRoundLabel = (depth: number, t: (key: string, params?: Record<string, unknown>) => string) => {
  if (depth <= 0) {
    return t("components.workspace.simulationHero.initialSetup");
  }
  return t("components.workspace.simulationHero.roundN", { n: depth });
};

export const SimulationHero: React.FC<SimulationHeroProps> = ({
  isGenerating,
  isCompareMode,
  canReturnToParent,
  onContinue,
  onCreateBranch,
  onViewDetails,
  onToggleCompare,
  onOpenNode,
  onReturnToParent,
}) => {
  const { t } = useTranslation();
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const nodes = useSimulationStore((state) => state.nodes);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const selectedProviderId = useSimulationStore((state) => state.selectedProviderId);
  const currentProviderId = useSimulationStore((state) => state.currentProviderId);
  const llmProviders = useSimulationStore((state) => state.llmProviders);

  const selectedNode = React.useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) || nodes[0] || null,
    [nodes, selectedNodeId],
  );

  const workspaceTitle = React.useMemo(() => {
    const rawTitle = currentSimulation?.name || t("simulationWorkspace.titleFallback");
    const [primaryTitle] = rawTitle.split(/\s[-–—]\s/);
    return primaryTitle?.trim() || rawTitle;
  }, [currentSimulation?.name, t]);

  const sceneConfig = (currentSimulation?.scene_config ?? {}) as Record<string, any>;
  const summary =
    sceneConfig.description ||
    sceneConfig.initial_event ||
    currentSimulation?.description ||
    t("simulationWorkspace.subtitleFallback");

  const compactSummary = React.useMemo(() => {
    const normalized = String(summary || "").replace(/\s+/g, " ").trim();
    if (!normalized) {
      return t("components.workspace.simulationHero.continueHint");
    }
    if (normalized.length <= 72) {
      return normalized;
    }
    return `${normalized.slice(0, 72).trim()}…`;
  }, [t, summary]);

  const runStatus = isGenerating
    ? t("simulationWorkspace.running")
    : t(`topologyExplorer.status.${selectedNode?.status || "pending"}`);

  const providerSelection = selectedProviderId ?? currentProviderId ?? null;
  const selectedProvider =
    llmProviders.find((provider) => provider.id === providerSelection) || null;

  return (
    <section className="ss-sim-hero" id="workspace-hero" aria-label={t("components.workspace.simulationHero.heroAriaLabel")}>
      <div className="ss-sim-hero__identity">
        <h1 className="ss-sim-hero__title">{workspaceTitle}</h1>
        <p className="ss-sim-hero__summary">{compactSummary}</p>
      </div>

      <div className="ss-sim-hero__key-facts" aria-label={t("components.workspace.simulationHero.keyFactsAriaLabel")}>
        <div className="ss-sim-hero__fact">
          <span>{t("components.workspace.simulationHero.round")}</span>
          <strong>{getRoundLabel(selectedNode?.depth || 0, t)}</strong>
        </div>
        <div className="ss-sim-hero__fact">
          <span>{t("components.workspace.simulationHero.status")}</span>
          <strong>{runStatus}</strong>
        </div>
        <div className="ss-sim-hero__fact">
          <span>{t("components.workspace.simulationHero.node")}</span>
          <strong>{getWorkspaceNodeLabel(selectedNode, t)}</strong>
        </div>
        <div className="ss-sim-hero__fact">
          <span>{t("components.workspace.simulationHero.model")}</span>
          <strong>
            {selectedProvider
              ? `${selectedProvider.name || selectedProvider.provider}${selectedProvider.model ? ` · ${selectedProvider.model}` : ""}`
              : t("simulationWorkspace.noProvider")}
          </strong>
        </div>
      </div>

      <div className="ss-sim-hero__actions">
        <button type="button" className="ss-sim-hero__primary" onClick={onContinue}>
          <Play size={16} />
          <span>{isGenerating ? t("simulationWorkspace.running") : t("controlRoom.continueSimulation")}</span>
        </button>

        <details className="ss-sim-hero__menu">
          <summary className="ss-sim-hero__menu-trigger" aria-label={t("components.workspace.simulationHero.moreActions")}>
            <MoreHorizontal size={16} />
          </summary>
          <div className="ss-sim-hero__menu-panel">
            <button type="button" className="ss-button-secondary" onClick={onCreateBranch}>
              <GitFork size={15} />
              {t("controlRoom.createBranchPrimary")}
            </button>
            <button type="button" className="ss-button-secondary" onClick={onViewDetails}>
              <Eye size={15} />
              {t("controlRoom.viewDetails")}
            </button>
            <button type="button" className="ss-button-secondary" onClick={onToggleCompare}>
              <GitCompareArrows size={15} />
              {isCompareMode ? t("simulationWorkspace.compareExit") : t("simulationWorkspace.compare")}
            </button>
            <button type="button" className="ss-button-secondary" onClick={onOpenNode}>
              <Eye size={15} />
              {t("components.workspace.simulationHero.openNode")}
            </button>
            <button type="button" className="ss-button-secondary" onClick={onReturnToParent} disabled={!canReturnToParent}>
              <ArrowUpLeft size={15} />
              {t("controlRoom.returnToParentBranch")}
            </button>
          </div>
        </details>
      </div>
    </section>
  );
};

export default SimulationHero;
