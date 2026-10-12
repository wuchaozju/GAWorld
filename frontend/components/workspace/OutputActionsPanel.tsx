import React from "react";
import { Download, FileText, Save } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useSimulationStore } from "../../store";

export const OutputActionsPanel: React.FC = () => {
  const { t } = useTranslation();
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const toggleExport = useSimulationStore((state) => state.toggleExport);
  const toggleReportModal = useSimulationStore((state) => state.toggleReportModal);
  const toggleSaveTemplate = useSimulationStore((state) => state.toggleSaveTemplate);

  const hasSimulation = Boolean(currentSimulation);

  return (
    <div className="ss-output-panel">
      <button
        type="button"
        onClick={() => toggleReportModal(true)}
        disabled={!hasSimulation}
        className="ss-output-panel__action"
      >
        <FileText size={15} />
        <span>{t("simulationWorkspace.report")}</span>
      </button>
      <button
        type="button"
        onClick={() => toggleExport(true)}
        disabled={!hasSimulation}
        className="ss-output-panel__action"
      >
        <Download size={15} />
        <span>{t("simulationWorkspace.export")}</span>
      </button>
      <button
        type="button"
        onClick={() => toggleSaveTemplate(true)}
        disabled={!hasSimulation}
        className="ss-output-panel__action"
      >
        <Save size={15} />
        <span>{t("simulationWorkspace.template")}</span>
      </button>
    </div>
  );
};

export default OutputActionsPanel;
