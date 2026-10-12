import React from "react";
import { useTranslation } from "react-i18next";

import { ObservationConsole } from "./ObservationConsole";

interface RoleObservationPanelProps {
  selectedAgentId: string | null;
  onSelectAgent: (agentId: string | null) => void;
  open: boolean;
  onToggle: () => void;
}

export const RoleObservationPanel: React.FC<RoleObservationPanelProps> = ({
  selectedAgentId,
  onSelectAgent,
  open,
  onToggle,
}) => {
  const { t } = useTranslation();

  return (
    <section className="ss-role-observation" id="workspace-role">
      <button type="button" onClick={onToggle} className="ss-role-observation__summary">
        <div>
          <div className="ss-kicker">{t("controlRoom.roleObservation")}</div>
          <h2>{t("components.workspace.roleObservation.title")}</h2>
          <p>{t("controlRoom.observationSecondaryCopy")}</p>
        </div>
        <span className="ss-role-observation__toggle">{open ? t("components.workspace.roleObservation.hide") : t("components.workspace.roleObservation.open")}</span>
      </button>

      {open ? (
        <div className="ss-role-observation__body">
          <ObservationConsole selectedAgentId={selectedAgentId} onSelectAgent={onSelectAgent} />
        </div>
      ) : null}
    </section>
  );
};

export default RoleObservationPanel;
