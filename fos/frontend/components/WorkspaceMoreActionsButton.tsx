/**
 * This file shows the extra actions button for the simulation workspace.
 *
 * `WorkspaceMoreActionsButton` opens the menu with provider, knowledge,
 * analytics, report, export, reset, and delete actions.
 */

import React from "react";
import { useTranslation } from "react-i18next";
import {
  BarChart2,
  Download,
  FileText,
  Globe,
  MoreHorizontal,
  RotateCcw,
  Trash2,
} from "lucide-react";

import { useSimulationStore } from "../store";
import { Button } from "./ui/button";

interface WorkspaceMoreActionsButtonProps {
  wrapperClassName?: string;
  triggerClassName?: string;
  panelClassName?: string;
  triggerTitle?: string;
  triggerLabel?: string;
}

const ProviderPicker: React.FC = () => {
  const { t } = useTranslation();
  const llmProviders = useSimulationStore((state) => state.llmProviders);
  const selectedProviderId = useSimulationStore((state) => state.selectedProviderId);
  const currentProviderId = useSimulationStore((state) => state.currentProviderId);
  const setSelectedProvider = useSimulationStore((state) => state.setSelectedProvider);
  const providerSelection = selectedProviderId ?? currentProviderId ?? null;

  return (
    <div
      className="rounded-xl border p-3 space-y-2"
      style={{ borderColor: "var(--ss-workspace-border)" }}
    >
      <div className="text-xs font-medium" style={{ color: "var(--ss-workspace-muted)" }}>
        {t("simPage.provider")}
      </div>
      <select
        value={providerSelection ?? ""}
        onChange={(event) => {
          const nextValue = event.target.value;
          setSelectedProvider(nextValue ? Number(nextValue) : null);
        }}
        className="w-full border rounded-full px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--ss-brand-primary)]"
        style={{ background: "var(--ss-surface)", borderColor: "var(--ss-border)" }}
      >
        <option value="">{t("simPage.selectProvider")}</option>
        {llmProviders.map((provider) => (
          <option key={provider.id} value={provider.id}>
            {provider.name || provider.provider} {provider.model ? `(${provider.model})` : ""}
          </option>
        ))}
      </select>
    </div>
  );
};

export const WorkspaceMoreActionsButton: React.FC<WorkspaceMoreActionsButtonProps> = ({
  wrapperClassName,
  triggerClassName,
  panelClassName,
  triggerTitle,
  triggerLabel,
}) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = React.useState(false);
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const toggleAnalytics = useSimulationStore((state) => state.toggleAnalytics);
  const toggleExport = useSimulationStore((state) => state.toggleExport);
  const toggleReportModal = useSimulationStore((state) => state.toggleReportModal);
  const setGlobalKnowledgeOpen = useSimulationStore((state) => state.setGlobalKnowledgeOpen);
  const resetSimulation = useSimulationStore((state) => state.resetSimulation);
  const deleteSimulation = useSimulationStore((state) => state.deleteSimulation);
  const isGenerating = useSimulationStore((state) => state.isGenerating);
  const hasSimulation = Boolean(currentSimulation);

  const handleResetSimulation = (): void => {
    if (!hasSimulation) {
      return;
    }
    if (!window.confirm(t("simPage.confirmReset"))) {
      return;
    }
    setIsOpen(false);
    void resetSimulation();
  };

  const handleDeleteSimulation = (): void => {
    if (!hasSimulation) {
      return;
    }
    if (!window.confirm(t("simPage.confirmDelete"))) {
      return;
    }
    setIsOpen(false);
    void deleteSimulation();
  };

  const resolvedTriggerLabel = triggerLabel ?? t("simPage.moreActions");
  const resolvedTriggerTitle = triggerTitle ?? resolvedTriggerLabel;

  return (
    <div className={wrapperClassName ?? "relative"}>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setIsOpen((current) => !current)}
        aria-label={resolvedTriggerLabel}
        title={resolvedTriggerTitle}
        className={triggerClassName}
      >
        <MoreHorizontal size={14} />
        {triggerLabel ? (
          <span className="text-xs font-medium text-center leading-tight whitespace-normal">
            {triggerLabel}
          </span>
        ) : null}
      </Button>

      {isOpen ? (
        <div
          className={
            panelClassName ??
            "absolute right-0 top-full mt-2 w-72 rounded-2xl border shadow-xl p-3 z-20"
          }
          style={{
            background: "var(--ss-workspace-surface)",
            borderColor: "var(--ss-workspace-border)",
          }}
        >
          <div className="space-y-2">
            <ProviderPicker />

            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setGlobalKnowledgeOpen(true);
                setIsOpen(false);
              }}
              className="w-full justify-start"
            >
              <Globe size={14} />
              {t("simPage.globalKnowledge")}
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                toggleAnalytics(true);
                setIsOpen(false);
              }}
              className="w-full justify-start"
            >
              <BarChart2 size={14} />
              {t("simPage.analytics")}
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                toggleReportModal(true);
                setIsOpen(false);
              }}
              className="w-full justify-start"
            >
              <FileText size={14} />
              {t("simPage.report")}
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                toggleExport(true);
                setIsOpen(false);
              }}
              className="w-full justify-start"
            >
              <Download size={14} />
              {t("simPage.export")}
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={handleResetSimulation}
              disabled={!hasSimulation || isGenerating}
              className="w-full justify-start"
            >
              <RotateCcw size={14} />
              {t("simPage.resetSimulation")}
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={handleDeleteSimulation}
              disabled={!hasSimulation || isGenerating}
              className="w-full justify-start !text-[var(--ss-danger-600)]"
            >
              <Trash2 size={14} />
              {t("simPage.deleteSimulation")}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default WorkspaceMoreActionsButton;
