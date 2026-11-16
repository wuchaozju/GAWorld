import React from "react";
import {
  BarChart2,
  Clock3,
  FileCog,
  GitFork,
  Globe,
  Network,
  Rows3,
  Sparkles,
  Zap,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { useSimulationStore } from "../../store";
import { buildWorkspacePath, getWorkspaceNodeLabel } from "./workspaceLabels";
import { CollapsibleInsightSection } from "./CollapsibleInsightSection";
import { OutputActionsPanel } from "./OutputActionsPanel";

interface AnalysisContextPanelProps {
  branchDetailsOpen: boolean;
  onToggleBranchDetails: () => void;
  onOpenRoleObservation: () => void;
}

export const AnalysisContextPanel: React.FC<AnalysisContextPanelProps> = ({
  branchDetailsOpen,
  onToggleBranchDetails,
  onOpenRoleObservation,
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
  const llmProviders = useSimulationStore((state) => state.llmProviders);
  const selectedProviderId = useSimulationStore((state) => state.selectedProviderId);
  const currentProviderId = useSimulationStore((state) => state.currentProviderId);
  const setSelectedProvider = useSimulationStore((state) => state.setSelectedProvider);
  const toggleNetworkEditor = useSimulationStore((state) => state.toggleNetworkEditor);
  const toggleTimeSettings = useSimulationStore((state) => state.toggleTimeSettings);
  const setGlobalKnowledgeOpen = useSimulationStore((state) => state.setGlobalKnowledgeOpen);
  const toggleAnalytics = useSimulationStore((state) => state.toggleAnalytics);
  const toggleExperimentDesigner = useSimulationStore((state) => state.toggleExperimentDesigner);
  const logs = useSimulationStore((state) => state.logs);
  const rawEvents = useSimulationStore((state) => state.rawEvents);
  const agents = useSimulationStore((state) => state.agents);

  const selectedNode = React.useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) || nodes[0] || null,
    [nodes, selectedNodeId],
  );
  const nodeLookup = React.useMemo(
    () => new Map(nodes.map((node) => [node.id, node])),
    [nodes],
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
  const currentPath = React.useMemo(
    () => buildWorkspacePath(selectedNode, nodeLookup),
    [nodeLookup, selectedNode],
  );

  const providerSelection = selectedProviderId ?? currentProviderId ?? null;
  const selectedProvider =
    llmProviders.find((provider) => provider.id === providerSelection) || null;
  const recentLogs = React.useMemo(() => [...logs].slice(-4).reverse(), [logs]);
  const sceneConfig = ((currentSimulation as any)?.scene_config || {}) as Record<string, any>;
  const actionSpace =
    sceneConfig.actions?.length ||
    sceneConfig.action_space?.length ||
    sceneConfig.heuristics?.length ||
    0;

  const handleActivateNode = (nodeId: string) => {
    if (isCompareMode && nodeId !== selectedNodeId) {
      setCompareTarget(nodeId);
      return;
    }
    selectNode(nodeId);
  };

  const metaRows = [
    {
      label: t("components.workspace.analysisContext.experiment"),
      value: currentSimulation?.name || t("simulationWorkspace.titleFallback"),
    },
    {
      label: t("components.workspace.analysisContext.path"),
      value: currentPath.length
        ? currentPath.map((node) => getWorkspaceNodeLabel(node, t)).join(" / ")
        : "—",
    },
    {
      label: t("components.workspace.analysisContext.worldTime"),
      value: selectedNode?.worldTime || "—",
    },
    {
      label: t("components.workspace.analysisContext.actionSpace"),
      value: String(actionSpace || "—"),
    },
  ];

  return (
    <aside className="ss-analysis-panel" id="workspace-analysis">
      <div className="ss-analysis-panel__header">
        <div className="ss-kicker">{t("components.workspace.analysisContext.title")}</div>
        <h2>{t("components.workspace.analysisContext.subtitle")}</h2>
        <p>
          {t("components.workspace.analysisContext.description")}
        </p>
      </div>

      <div className="ss-analysis-panel__body">
        <CollapsibleInsightSection
          title={t("components.workspace.analysisContext.branchDetailsTitle")}
          subtitle={t("components.workspace.analysisContext.branchDetailsSubtitle")}
          badge={
            <span>
              {t("components.workspace.analysisContext.parentShort")} {parentNode ? 1 : 0} / {t("components.workspace.analysisContext.siblingShort")} {siblingNodes.length} / {t("components.workspace.analysisContext.childShort")}{" "}
              {childNodes.length}
            </span>
          }
          open={branchDetailsOpen}
          onToggle={onToggleBranchDetails}
          tone="details"
        >
          <div className="ss-analysis-panel__meta-grid">
            <div className="ss-analysis-panel__meta-chip">
              <span>{t("components.workspace.analysisContext.current")}</span>
              <strong>{getWorkspaceNodeLabel(selectedNode, t)}</strong>
            </div>
            <div className="ss-analysis-panel__meta-chip">
              <span>{t("components.workspace.analysisContext.compare")}</span>
              <strong>
                {compareTargetNodeId
                  ? getWorkspaceNodeLabel(nodes.find((node) => node.id === compareTargetNodeId) || null, t)
                  : t("components.workspace.analysisContext.noneSelected")}
              </strong>
            </div>
          </div>

          <div className="ss-analysis-panel__branch-group">
            <div className="ss-analysis-panel__branch-block">
              <div className="ss-analysis-panel__branch-label">{t("controlRoom.parentBranch")}</div>
              {parentNode ? (
                <button
                  type="button"
                  onClick={() => handleActivateNode(parentNode.id)}
                  className="ss-analysis-panel__branch-item"
                >
                  <strong>{getWorkspaceNodeLabel(parentNode, t)}</strong>
                  <span>{parentNode.display_id || parentNode.id}</span>
                </button>
              ) : (
                <div className="ss-analysis-panel__empty">{t("controlRoom.noParentBranch")}</div>
              )}
            </div>

            <div className="ss-analysis-panel__branch-block">
              <div className="ss-analysis-panel__branch-label">{t("controlRoom.siblingBranches")}</div>
              {siblingNodes.length ? (
                siblingNodes.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => handleActivateNode(node.id)}
                    className={`ss-analysis-panel__branch-item${node.id === compareTargetNodeId ? " is-compare" : ""}`}
                  >
                    <strong>{getWorkspaceNodeLabel(node, t)}</strong>
                    <span>{node.display_id || node.id}</span>
                  </button>
                ))
              ) : (
                <div className="ss-analysis-panel__empty">{t("controlRoom.noSiblingBranches")}</div>
              )}
            </div>

            <div className="ss-analysis-panel__branch-block">
              <div className="ss-analysis-panel__branch-label">{t("controlRoom.childBranches")}</div>
              {childNodes.length ? (
                childNodes.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => handleActivateNode(node.id)}
                    className="ss-analysis-panel__branch-item"
                  >
                    <strong>{getWorkspaceNodeLabel(node, t)}</strong>
                    <span>{node.display_id || node.id}</span>
                  </button>
                ))
              ) : (
                <div className="ss-analysis-panel__empty">{t("controlRoom.noChildBranches")}</div>
              )}
            </div>
          </div>
        </CollapsibleInsightSection>

        <CollapsibleInsightSection
          title={t("components.workspace.analysisContext.configTitle")}
          subtitle={t("components.workspace.analysisContext.configSubtitle")}
          defaultOpen
          tone="details"
        >
          <div className="ss-analysis-panel__provider">
            {llmProviders.length === 0 ? (
              <div className="ss-analysis-panel__empty">
                <div>
                  {t("components.workspace.analysisContext.noLlmProvider")}
                </div>
                <button
                  type="button"
                  onClick={() => navigate("/settings?tab=providers_llm")}
                  className="ss-button-secondary mt-3"
                >
                  {t("components.workspace.analysisContext.openSettings")}
                </button>
              </div>
            ) : null}

            <label>
              <span>{t("simulationWorkspace.provider")}</span>
              <select
                value={providerSelection ?? ""}
                onChange={(event) => {
                  const value = event.target.value;
                  setSelectedProvider(value ? Number(value) : null);
                }}
              >
                <option value="">{t("simulationWorkspace.noProvider")}</option>
                {llmProviders.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name || provider.provider}
                    {provider.model ? ` · ${provider.model}` : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="ss-analysis-panel__tool-grid">
            <button type="button" onClick={() => toggleExperimentDesigner(true)} className="ss-analysis-panel__tool">
              <FileCog size={15} />
              <span>{t("simulationWorkspace.experiment")}</span>
            </button>
            <button type="button" onClick={() => toggleNetworkEditor(true)} className="ss-analysis-panel__tool">
              <Network size={15} />
              <span>{t("simulationWorkspace.network")}</span>
            </button>
            <button type="button" onClick={() => toggleTimeSettings(true)} className="ss-analysis-panel__tool">
              <Clock3 size={15} />
              <span>{t("simulationWorkspace.time")}</span>
            </button>
            <button type="button" onClick={() => setGlobalKnowledgeOpen(true)} className="ss-analysis-panel__tool">
              <Globe size={15} />
              <span>{t("simulationWorkspace.knowledge")}</span>
            </button>
            <button type="button" onClick={() => toggleAnalytics(true)} className="ss-analysis-panel__tool">
              <BarChart2 size={15} />
              <span>{t("simulationWorkspace.analytics")}</span>
            </button>
            <button type="button" onClick={onOpenRoleObservation} className="ss-analysis-panel__tool">
              <Rows3 size={15} />
              <span>{t("controlRoom.roleObservation")}</span>
            </button>
          </div>
        </CollapsibleInsightSection>

        <CollapsibleInsightSection
          title={t("components.workspace.analysisContext.worldRulesTitle")}
          subtitle={t("components.workspace.analysisContext.worldRulesSubtitle")}
          defaultOpen
          tone="metrics"
        >
          <div className="ss-analysis-panel__facts">
            {metaRows.map((row) => (
              <div key={row.label} className="ss-analysis-panel__fact">
                <span>{row.label}</span>
                <strong>{row.value}</strong>
              </div>
            ))}
          </div>

          <div className="ss-analysis-panel__metrics">
            <div className="ss-analysis-panel__metric">
              <span>{t("components.workspace.analysisContext.agentsLabel")}</span>
              <strong>{agents.length}</strong>
            </div>
            <div className="ss-analysis-panel__metric">
              <span>{t("components.workspace.analysisContext.logsLabel")}</span>
              <strong>{logs.length}</strong>
            </div>
            <div className="ss-analysis-panel__metric">
              <span>{t("components.workspace.analysisContext.eventsLabel")}</span>
              <strong>{rawEvents.length}</strong>
            </div>
            <div className="ss-analysis-panel__metric">
              <span>{t("components.workspace.analysisContext.modeLabel")}</span>
              <strong>{isCompareMode ? t("simulationWorkspace.compare") : t("components.workspace.analysisContext.controlMode")}</strong>
            </div>
          </div>
        </CollapsibleInsightSection>

        <CollapsibleInsightSection
          title={t("components.workspace.analysisContext.researchLogsTitle")}
          subtitle={t("components.workspace.analysisContext.researchLogsSubtitle")}
          tone="logs"
        >
          {recentLogs.length ? (
            <div className="ss-analysis-panel__log-list">
              {recentLogs.map((entry) => (
                <div key={entry.id} className="ss-analysis-panel__log-item">
                  <div className="ss-analysis-panel__log-meta">
                    <span>{entry.agentId || t("components.workspace.analysisContext.systemLabel")}</span>
                    <strong>{entry.round ? `R${entry.round}` : "—"}</strong>
                  </div>
                  <p>{entry.content}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="ss-analysis-panel__empty">
              {t("components.workspace.analysisContext.noLogsYet")}
            </div>
          )}
        </CollapsibleInsightSection>

        <CollapsibleInsightSection
          title={t("components.workspace.analysisContext.exportsTitle")}
          subtitle={t("components.workspace.analysisContext.exportsSubtitle")}
          tone="outputs"
        >
          <OutputActionsPanel />

          <div className="ss-analysis-panel__tool-grid">
            <button type="button" onClick={() => onToggleBranchDetails()} className="ss-analysis-panel__tool">
              <GitFork size={15} />
              <span>{branchDetailsOpen ? t("controlRoom.hideBranchDetails") : t("controlRoom.showBranchDetails")}</span>
            </button>
            <button
              type="button"
              onClick={() => {
                if (isCompareMode) {
                  toggleCompareMode(false);
                  setCompareTarget(null);
                  return;
                }
                toggleCompareMode(true);
              }}
              className="ss-analysis-panel__tool"
            >
              <Sparkles size={15} />
              <span>{isCompareMode ? t("simulationWorkspace.compareExit") : t("simulationWorkspace.compare")}</span>
            </button>
          </div>
        </CollapsibleInsightSection>
      </div>
    </aside>
  );
};

export default AnalysisContextPanel;
