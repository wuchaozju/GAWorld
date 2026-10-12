import React from "react";
import { BarChart2, ChevronRight, Clock3, FileText, Globe, PauseCircle, Save, Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { useSimulationStore } from "../../store";
import { buildWorkspacePath, getWorkspaceNodeLabel } from "./workspaceLabels";
import { CollapsibleInsightSection } from "./CollapsibleInsightSection";

interface SimulationSummaryRailProps {
  onOpenLogs: () => void;
  onHide: () => void;
}

export const SimulationSummaryRail: React.FC<SimulationSummaryRailProps> = ({ onOpenLogs, onHide }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const nodes = useSimulationStore((state) => state.nodes);
  const logs = useSimulationStore((state) => state.logs);
  const rawEvents = useSimulationStore((state) => state.rawEvents);
  const agents = useSimulationStore((state) => state.agents);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const selectedProviderId = useSimulationStore((state) => state.selectedProviderId);
  const currentProviderId = useSimulationStore((state) => state.currentProviderId);
  const llmProviders = useSimulationStore((state) => state.llmProviders);
  const toggleTimeSettings = useSimulationStore((state) => state.toggleTimeSettings);
  const toggleReportModal = useSimulationStore((state) => state.toggleReportModal);
  const toggleExport = useSimulationStore((state) => state.toggleExport);
  const toggleSaveTemplate = useSimulationStore((state) => state.toggleSaveTemplate);

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

  const providerSelection = selectedProviderId ?? currentProviderId ?? null;
  const selectedProvider =
    llmProviders.find((provider) => provider.id === providerSelection) || null;
  const sceneConfig = (currentSimulation?.scene_config ?? {}) as Record<string, any>;
  const selectedNodeLogCount = logs.filter((entry) => entry.nodeId === selectedNodeId).length;
  const xihuMaterials = Array.isArray(sceneConfig.xihu_material_refs) ? sceneConfig.xihu_material_refs : [];
  const xihuBenchmarks = (sceneConfig.xihu_benchmarks?.metrics ?? {}) as Record<
    string,
    { label: string; mean: number; count: number }
  >;
  const xihuBenchmarkEntries = Object.values(xihuBenchmarks).slice(0, 6);

  const summaryFacts = [
    {
      label: t("components.workspace.summaryRail.worldModel"),
      value: sceneConfig.name || sceneConfig.scene_type || currentSimulation?.name || "—",
    },
    {
      label: t("components.workspace.summaryRail.reasoningModel"),
      value: selectedProvider
        ? `${selectedProvider.name || selectedProvider.provider}${selectedProvider.model ? ` · ${selectedProvider.model}` : ""}`
        : t("simulationWorkspace.noProvider"),
    },
    {
      label: t("components.workspace.summaryRail.mode"),
      value: t("simPage.fosEngine"),
    },
    {
      label: t("components.workspace.summaryRail.currentRound"),
      value: selectedNode?.depth != null ? String(selectedNode.depth) : "0",
    },
    {
      label: t("components.workspace.summaryRail.timestamp"),
      value: selectedNode?.worldTime || "—",
    },
    {
      label: t("components.workspace.summaryRail.primaryBranch"),
      value: selectedNode?.display_id || selectedNode?.id || "—",
    },
  ];

  const worldRules = [
    {
      label: t("components.workspace.summaryRail.worldSummary"),
      value: sceneConfig.description || sceneConfig.initial_event || t("components.workspace.summaryRail.noWorldSummary"),
    },
    {
      label: t("components.workspace.summaryRail.coreConstraints"),
      value: sceneConfig.constraints || sceneConfig.rules || t("components.workspace.summaryRail.defaultConstraints"),
    },
    {
      label: t("components.workspace.summaryRail.experimentGoal"),
      value: sceneConfig.goal || sceneConfig.objective || currentSimulation?.description || t("components.workspace.summaryRail.defaultGoal"),
    },
    {
      label: t("components.workspace.summaryRail.termination"),
      value: sceneConfig.termination || sceneConfig.stop_condition || t("components.workspace.summaryRail.defaultTermination"),
    },
  ];

  const metrics = [
    { label: t("components.workspace.summaryRail.branches"), value: Math.max(nodes.length - 1, 0) },
    { label: t("components.workspace.summaryRail.nodesCount"), value: nodes.length },
    { label: t("components.workspace.summaryRail.agentsCount"), value: agents.length },
    { label: t("components.workspace.summaryRail.currentEvents"), value: selectedNodeLogCount },
    { label: t("components.workspace.summaryRail.logsCount"), value: logs.length },
    { label: t("components.workspace.summaryRail.rawEvents"), value: rawEvents.length },
  ];

  return (
    <aside className="ss-summary-rail" id="workspace-summary">
      <div className="ss-summary-rail__header">
        <div>
          <div className="ss-kicker">{t("components.workspace.summaryRail.statusKicker")}</div>
          <h2>{t("components.workspace.summaryRail.title")}</h2>
          <p>{t("components.workspace.summaryRail.headerSubtitle")}</p>
        </div>
        <button
          type="button"
          className="ss-icon-button"
          onClick={onHide}
          title={t("components.workspace.summaryRail.hideTitle")}
        >
          <ChevronRight size={16} />
        </button>
      </div>

      <div className="ss-summary-rail__body">
        <CollapsibleInsightSection
          title={t("components.workspace.summaryRail.simConfigTitle")}
          subtitle={currentPath.length ? currentPath.map((node) => getWorkspaceNodeLabel(node, t)).join(" / ") : "—"}
          defaultOpen={false}
          tone="details"
        >
          <div className="ss-summary-rail__fact-grid">
            {summaryFacts.map((fact) => (
              <div key={fact.label} className="ss-summary-rail__fact">
                <span>{fact.label}</span>
                <strong>{fact.value}</strong>
              </div>
            ))}
          </div>
        </CollapsibleInsightSection>

        <CollapsibleInsightSection
          title={t("components.workspace.summaryRail.worldRulesTitle")}
          subtitle={t("components.workspace.summaryRail.worldRulesSubtitle")}
          defaultOpen={false}
          tone="details"
        >
          <div className="ss-summary-rail__rule-list">
            {worldRules.map((rule) => (
              <div key={rule.label} className="ss-summary-rail__rule">
                <span>{rule.label}</span>
                <p>{rule.value}</p>
              </div>
            ))}
          </div>
        </CollapsibleInsightSection>

        {sceneConfig.xihu_arm_id ? (
          <CollapsibleInsightSection
            title={t("components.workspace.summaryRail.xihuArm")}
            subtitle={sceneConfig.xihu_arm_label || sceneConfig.xihu_arm_id}
            defaultOpen={false}
            tone="details"
          >
            <div className="ss-summary-rail__rule-list">
              <div className="ss-summary-rail__rule">
                <span>{t("components.workspace.summaryRail.armFraming")}</span>
                <p>{sceneConfig.xihu_arm_summary || "—"}</p>
              </div>
              <div className="ss-summary-rail__rule">
                <span>{t("components.workspace.summaryRail.importedPackage")}</span>
                <p>{sceneConfig.xihu_package_title || sceneConfig.xihu_package_id || "—"}</p>
              </div>
            </div>

            {xihuMaterials.length ? (
              <div className="ss-summary-rail__rule-list">
                {xihuMaterials.map((material: any) => (
                  <div key={material.id} className="ss-summary-rail__rule">
                    <span>{material.kindLabel || material.kind}</span>
                    <p>{material.displayTitle}</p>
                    <p>{material.textSummary}</p>
                    {material.downloadUrl ? (
                      <a
                        href={material.downloadUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs font-semibold text-blue-600 hover:text-blue-800"
                      >
                        {t("components.workspace.summaryRail.openSourceFile")}
                      </a>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}

            {xihuBenchmarkEntries.length ? (
              <div className="ss-summary-rail__metric-grid">
                {xihuBenchmarkEntries.map((metric) => (
                  <div key={metric.label} className="ss-summary-rail__metric">
                    <span>{metric.label}</span>
                    <strong>{metric.mean}</strong>
                  </div>
                ))}
              </div>
            ) : null}
          </CollapsibleInsightSection>
        ) : null}

        <CollapsibleInsightSection
          title={t("components.workspace.summaryRail.systemMetrics")}
          subtitle={t("components.workspace.summaryRail.metricsSubtitle")}
          defaultOpen={false}
          tone="metrics"
        >
          <div className="ss-summary-rail__metric-grid">
            {metrics.map((metric) => (
              <div key={metric.label} className="ss-summary-rail__metric">
                <span>{metric.label}</span>
                <strong>{metric.value}</strong>
              </div>
            ))}
          </div>
        </CollapsibleInsightSection>

        <CollapsibleInsightSection
          title={t("components.workspace.summaryRail.actions")}
          subtitle={t("components.workspace.summaryRail.actionsSubtitle")}
          defaultOpen={false}
          tone="outputs"
        >
          <div className="ss-summary-rail__action-grid">
            <button type="button" className="ss-summary-rail__action" onClick={() => toggleSaveTemplate(true)}>
              <Save size={15} />
              <span>{t("components.workspace.summaryRail.saveTemplate")}</span>
            </button>
            <button type="button" className="ss-summary-rail__action" onClick={() => toggleTimeSettings(true)}>
              <Clock3 size={15} />
              <span>{t("components.workspace.summaryRail.timeSettings")}</span>
            </button>
            <button type="button" className="ss-summary-rail__action" onClick={() => toggleReportModal(true)}>
              <FileText size={15} />
              <span>{t("components.workspace.summaryRail.openReport")}</span>
            </button>
            <button type="button" className="ss-summary-rail__action" onClick={() => toggleExport(true)}>
              <BarChart2 size={15} />
              <span>{t("components.workspace.summaryRail.exportResults")}</span>
            </button>
            <button type="button" className="ss-summary-rail__action" onClick={onOpenLogs}>
              <Globe size={15} />
              <span>{t("components.workspace.summaryRail.openResearchLogs")}</span>
            </button>
            <button type="button" className="ss-summary-rail__action is-danger" onClick={() => navigate("/settings")}>
              <Settings2 size={15} />
              <span>{t("components.workspace.summaryRail.settings")}</span>
            </button>
          </div>

          <div className="ss-summary-rail__pause-note">
            <PauseCircle size={15} />
            <span>{t("components.workspace.summaryRail.pauseNote")}</span>
          </div>
        </CollapsibleInsightSection>
      </div>
    </aside>
  );
};

export default SimulationSummaryRail;
