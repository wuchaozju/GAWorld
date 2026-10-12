import React from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  BarChart2,
  Beaker,
  Clock3,
  Download,
  FileText,
  GitFork,
  Globe,
  Loader2,
  Network,
  Play,
  RotateCcw,
  Save,
  Split,
  Trash2,
  Zap,
} from "lucide-react";

import { useSimulationStore } from "../../store";

type ActionButtonProps = {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  active?: boolean;
  primary?: boolean;
  caption?: string;
};

const ControlAction: React.FC<ActionButtonProps> = ({
  icon,
  label,
  onClick,
  disabled,
  danger,
  active,
  primary,
  caption,
}) => (
  <button
    onClick={onClick}
    disabled={disabled}
    className={[
      "ss-config-panel__action",
      danger ? "is-danger" : "",
      active ? "is-active" : "",
      primary ? "is-primary" : "",
    ]
      .filter(Boolean)
      .join(" ")}
  >
    <span className="ss-config-panel__action-icon">{icon}</span>
    <span className="ss-config-panel__action-copy">
      <strong>{label}</strong>
      {caption ? <span>{caption}</span> : null}
    </span>
  </button>
);

interface SimulationControlPanelProps {
  onRequestCreateBranch: () => void;
  onToggleBranchDetails: () => void;
  branchDetailsOpen: boolean;
  workspaceMode: "observation" | "control";
}

export const SimulationControlPanel: React.FC<SimulationControlPanelProps> = ({
  onRequestCreateBranch,
  onToggleBranchDetails,
  branchDetailsOpen,
  workspaceMode,
}) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const selectedNode = useSimulationStore((state) =>
    state.nodes.find((node) => node.id === state.selectedNodeId) || state.nodes[0] || null,
  );
  const advanceSimulation = useSimulationStore((state) => state.advanceSimulation);
  const toggleAnalytics = useSimulationStore((state) => state.toggleAnalytics);
  const toggleExport = useSimulationStore((state) => state.toggleExport);
  const toggleExperimentDesigner = useSimulationStore((state) => state.toggleExperimentDesigner);
  const toggleTimeSettings = useSimulationStore((state) => state.toggleTimeSettings);
  const toggleSaveTemplate = useSimulationStore((state) => state.toggleSaveTemplate);
  const toggleNetworkEditor = useSimulationStore((state) => state.toggleNetworkEditor);
  const toggleReportModal = useSimulationStore((state) => state.toggleReportModal);
  const setGlobalKnowledgeOpen = useSimulationStore((state) => state.setGlobalKnowledgeOpen);
  const openSyncModal = useSimulationStore((state) => state.openSyncModal);
  const resetSimulation = useSimulationStore((state) => state.resetSimulation);
  const deleteSimulation = useSimulationStore((state) => state.deleteSimulation);
  const isCompareMode = useSimulationStore((state) => state.isCompareMode);
  const toggleCompareMode = useSimulationStore((state) => state.toggleCompareMode);
  const setCompareTarget = useSimulationStore((state) => state.setCompareTarget);
  const isGenerating = useSimulationStore((state) => state.isGenerating);
  const llmProviders = useSimulationStore((state) => state.llmProviders);
  const selectedProviderId = useSimulationStore((state) => state.selectedProviderId);
  const currentProviderId = useSimulationStore((state) => state.currentProviderId);
  const setSelectedProvider = useSimulationStore((state) => state.setSelectedProvider);

  const hasSimulation = Boolean(currentSimulation);
  const providerSelection = selectedProviderId ?? currentProviderId ?? null;
  const selectedProvider =
    llmProviders.find((provider) => provider.id === providerSelection) || null;
  const isObservationMode = workspaceMode === "observation";

  const handleToggleCompare = () => {
    if (isCompareMode) {
      toggleCompareMode(false);
      setCompareTarget(null);
      return;
    }
    toggleCompareMode(true);
  };

  return (
    <aside className="ss-workspace__panel ss-workspace__panel--control ss-config-panel">
      <div className="ss-workspace__panel-header">
        <div className="ss-kicker">{t("controlRoom.controlPanelKicker")}</div>
        <h2 className="ss-workspace__panel-title mt-2">{t("controlRoom.controlPanelTitle")}</h2>
        <p className="ss-workspace__panel-copy">{t("controlRoom.controlPanelSubtitle")}</p>
      </div>

      <div className="ss-config-panel__body">
        <section className="ss-config-panel__group">
          <div className="ss-config-panel__group-head">
            <div className="ss-config-panel__group-title">
              {t("controlRoom.primaryActionsTitle")}
            </div>
            <p>
              {t("controlRoom.primaryActionsCopy")}
            </p>
          </div>

          <div className="ss-config-panel__stack">
            <ControlAction
              icon={isGenerating ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
              label={
                isGenerating
                  ? t("simulationWorkspace.running")
                  : t("controlRoom.continueSimulation")
              }
              caption={t("controlRoom.advanceCopy")}
              onClick={() => void advanceSimulation()}
              disabled={!selectedNodeId || isGenerating || isCompareMode}
              primary
            />
            <ControlAction
              icon={isGenerating ? <Loader2 size={15} className="animate-spin" /> : <GitFork size={15} />}
              label={t("controlRoom.createBranchPrimary")}
              caption={t("controlRoom.createBranchSidebarCopy")}
              onClick={onRequestCreateBranch}
              disabled={!selectedNodeId || isGenerating || isCompareMode}
            />
            <ControlAction
              icon={<Split size={15} />}
              label={isCompareMode ? t("simulationWorkspace.compareExit") : t("simulationWorkspace.compare")}
              caption={t("controlRoom.compareModeCopy")}
              onClick={handleToggleCompare}
              disabled={!hasSimulation}
              active={isCompareMode}
            />
            <ControlAction
              icon={<Beaker size={15} />}
              label={isObservationMode ? t("controlRoom.viewDetails") : t("simulationWorkspace.experiment")}
              caption={t("controlRoom.experimentDesignCopy")}
              onClick={() => toggleExperimentDesigner(true)}
              disabled={!hasSimulation}
            />
            {isObservationMode ? (
              <ControlAction
                icon={<Download size={15} />}
                label={t("simulationWorkspace.export")}
                caption={t("controlRoom.exportCopy")}
                onClick={() => toggleExport(true)}
                disabled={!hasSimulation}
              />
            ) : null}
          </div>

          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mt-3">
            <p className="text-xs text-amber-700">
              {t("controlRoom.researchNote")}
            </p>
          </div>
        </section>

        {!isObservationMode ? (
        <section className="ss-config-panel__group">
          <div className="ss-config-panel__group-head">
            <div className="ss-config-panel__group-title">{t("controlRoom.configurationTitle")}</div>
            <p>{t("controlRoom.configurationCopy")}</p>
          </div>

          <label className="ss-config-panel__provider">
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

          {llmProviders.length === 0 ? (
            <div className="ss-config-panel__meta">
              <span>{t("controlRoom.activeProvider")}</span>
              <strong>
                {t("components.workspace.simulationControl.noLlmProvider")}
              </strong>
              <button
                type="button"
                className="ss-button-secondary mt-3"
                onClick={() => navigate("/settings?tab=providers_llm")}
              >
                {t("components.workspace.simulationControl.openSettings")}
              </button>
            </div>
          ) : null}

          <div className="ss-config-panel__stack">
            <ControlAction
              icon={<Network size={15} />}
              label={t("simulationWorkspace.network")}
              caption={t("controlRoom.networkCopy")}
              onClick={() => toggleNetworkEditor(true)}
              disabled={!hasSimulation}
              active={false}
            />
            <ControlAction
              icon={<Clock3 size={15} />}
              label={t("simulationWorkspace.time")}
              caption={t("controlRoom.timeCopy")}
              onClick={() => toggleTimeSettings(true)}
              disabled={!hasSimulation}
            />
            <ControlAction
              icon={<Globe size={15} />}
              label={t("simulationWorkspace.knowledge")}
              caption={t("controlRoom.knowledgeCopy")}
              onClick={() => setGlobalKnowledgeOpen(true)}
              disabled={!hasSimulation}
            />
            <ControlAction
              icon={<BarChart2 size={15} />}
              label={t("simulationWorkspace.analytics")}
              caption={t("controlRoom.analyticsCopy")}
              onClick={() => toggleAnalytics(true)}
              disabled={!hasSimulation}
            />
          </div>

          <div className="ss-config-panel__meta">
            <span>{t("controlRoom.activeProvider")}</span>
            <strong>
              {selectedProvider
                ? `${selectedProvider.name || selectedProvider.provider}${selectedProvider.model ? ` · ${selectedProvider.model}` : ""}`
                : t("simulationWorkspace.noProvider")}
            </strong>
          </div>
        </section>
        ) : null}

        {!isObservationMode ? (
        <section className="ss-config-panel__group">
          <div className="ss-config-panel__group-head">
            <div className="ss-config-panel__group-title">{t("controlRoom.outputTitle")}</div>
            <p>{t("controlRoom.outputCopy")}</p>
          </div>

          <div className="ss-config-panel__stack">
            <ControlAction
              icon={<FileText size={15} />}
              label={t("simulationWorkspace.report")}
              caption={t("controlRoom.reportCopy")}
              onClick={() => toggleReportModal(true)}
              disabled={!hasSimulation}
            />
            <ControlAction
              icon={<Download size={15} />}
              label={t("simulationWorkspace.export")}
              caption={t("controlRoom.exportCopy")}
              onClick={() => toggleExport(true)}
              disabled={!hasSimulation}
            />
            <ControlAction
              icon={<Save size={15} />}
              label={t("simulationWorkspace.template")}
              caption={t("controlRoom.templateCopy")}
              onClick={() => toggleSaveTemplate(true)}
              disabled={!hasSimulation}
            />
          </div>
        </section>
        ) : null}

        {!isObservationMode ? (
        <section className="ss-config-panel__group">
          <div className="ss-config-panel__group-head">
            <div className="ss-config-panel__group-title">{t("controlRoom.branchToolsTitle")}</div>
            <p>{t("controlRoom.branchToolsCopy")}</p>
          </div>

          <div className="ss-config-panel__stack">
            <ControlAction
              icon={isGenerating ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
              label={
                isGenerating
                  ? t("simulationWorkspace.running")
                  : t("controlRoom.continueSimulation")
              }
              caption={t("controlRoom.advanceCopy")}
              onClick={() => void advanceSimulation()}
              disabled={!selectedNodeId || isGenerating || isCompareMode}
              primary
            />
            <ControlAction
              icon={<GitFork size={15} />}
              label={
                branchDetailsOpen
                  ? t("controlRoom.hideBranchDetails")
                  : t("controlRoom.showBranchDetails")
              }
              caption={t("controlRoom.branchRelationsCopy")}
              onClick={onToggleBranchDetails}
              disabled={!selectedNode}
              active={branchDetailsOpen}
            />
          </div>
        </section>
        ) : null}

        <details className="ss-config-panel__advanced">
          <summary>{t("simulationWorkspace.developerTools")}</summary>
          <div className="ss-config-panel__advanced-body">
            {isObservationMode ? (
              <>
                <label className="ss-config-panel__provider">
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
                <ControlAction
                  icon={<GitFork size={15} />}
                  label={
                    branchDetailsOpen
                      ? t("controlRoom.hideBranchDetails")
                      : t("controlRoom.showBranchDetails")
                  }
                  caption={t("controlRoom.branchRelationsCopy")}
                  onClick={onToggleBranchDetails}
                  disabled={!selectedNode}
                  active={branchDetailsOpen}
                />
                <ControlAction
                  icon={<Network size={15} />}
                  label={t("simulationWorkspace.network")}
                  caption={t("controlRoom.networkCopy")}
                  onClick={() => toggleNetworkEditor(true)}
                  disabled={!hasSimulation}
                />
                <ControlAction
                  icon={<Clock3 size={15} />}
                  label={t("simulationWorkspace.time")}
                  caption={t("controlRoom.timeCopy")}
                  onClick={() => toggleTimeSettings(true)}
                  disabled={!hasSimulation}
                />
                <ControlAction
                  icon={<BarChart2 size={15} />}
                  label={t("simulationWorkspace.analytics")}
                  caption={t("controlRoom.analyticsCopy")}
                  onClick={() => toggleAnalytics(true)}
                  disabled={!hasSimulation}
                />
                <ControlAction
                  icon={<FileText size={15} />}
                  label={t("simulationWorkspace.report")}
                  caption={t("controlRoom.reportCopy")}
                  onClick={() => toggleReportModal(true)}
                  disabled={!hasSimulation}
                />
              </>
            ) : null}
            <ControlAction
              icon={<Zap size={15} />}
              label={t("simulationWorkspace.sync")}
              onClick={openSyncModal}
              disabled={!hasSimulation}
            />
            <ControlAction
              icon={<RotateCcw size={15} />}
              label={t("simulationWorkspace.reset")}
              onClick={() => {
                if (window.confirm(t("simPage.confirmReset"))) {
                  void resetSimulation();
                }
              }}
              disabled={!hasSimulation || isGenerating}
            />
            <ControlAction
              icon={<Trash2 size={15} />}
              label={t("simulationWorkspace.delete")}
              onClick={() => {
                if (window.confirm(t("simPage.confirmDelete"))) {
                  void deleteSimulation();
                }
              }}
              disabled={!hasSimulation || isGenerating}
              danger
            />
          </div>
        </details>
      </div>
    </aside>
  );
};

export default SimulationControlPanel;
