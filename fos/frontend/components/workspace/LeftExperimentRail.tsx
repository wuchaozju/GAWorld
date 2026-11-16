import React from "react";
import {
  BookOpen,
  FileText,
  GitBranchPlus,
  LayoutDashboard,
  Orbit,
  Route,
  Settings2,
  UserRound,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAuthStore } from "../../store/auth";

export type RailSection =
  | "overview"
  | "flow"
  | "branches"
  | "agents"
  | "logs"
  | "reports"
  | "settings";

interface LeftExperimentRailProps {
  activeSection: RailSection;
  onOpenOverview: () => void;
  onOpenFlow: () => void;
  onOpenBranches: () => void;
  onOpenAgents: () => void;
  onOpenLogs: () => void;
  onOpenReports: () => void;
  onOpenSettings: () => void;
}

const NAV_ITEMS = [
  { id: "overview", icon: LayoutDashboard },
  { id: "flow", icon: Route },
  { id: "branches", icon: GitBranchPlus },
  { id: "agents", icon: UserRound },
  { id: "logs", icon: BookOpen },
  { id: "reports", icon: FileText },
  { id: "settings", icon: Settings2 },
] as const;

export const LeftExperimentRail: React.FC<LeftExperimentRailProps> = ({
  activeSection,
  onOpenOverview,
  onOpenFlow,
  onOpenBranches,
  onOpenAgents,
  onOpenLogs,
  onOpenReports,
  onOpenSettings,
}) => {
  const { t } = useTranslation();
  const user = useAuthStore((state) => state.user);

  const labelMap: Record<RailSection, string> = {
    overview: t("components.workspace.leftRail.overview"),
    flow: t("components.workspace.leftRail.flow"),
    branches: t("components.workspace.leftRail.branches"),
    agents: t("components.workspace.leftRail.agents"),
    logs: t("components.workspace.leftRail.logs"),
    reports: t("components.workspace.leftRail.reports"),
    settings: t("nav.settings"),
  };

  const clickMap: Record<RailSection, () => void> = {
    overview: onOpenOverview,
    flow: onOpenFlow,
    branches: onOpenBranches,
    agents: onOpenAgents,
    logs: onOpenLogs,
    reports: onOpenReports,
    settings: onOpenSettings,
  };

  return (
    <aside className="ss-cockpit-rail">
      <div className="ss-cockpit-rail__brand">
        <div className="ss-cockpit-rail__brand-mark">
          <Orbit size={18} />
        </div>
        <span>FOS</span>
      </div>

      <div className="ss-cockpit-rail__nav">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = activeSection === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={clickMap[item.id]}
              className={`ss-cockpit-rail__item${isActive ? " is-active" : ""}`}
              title={labelMap[item.id]}
            >
              <Icon size={18} />
              <span>{labelMap[item.id]}</span>
            </button>
          );
        })}
      </div>

      <div className="ss-cockpit-rail__footer">
        <button type="button" onClick={onOpenSettings} className="ss-cockpit-rail__account">
          <div className="ss-cockpit-rail__avatar">{String(user?.email || "S").slice(0, 1).toUpperCase()}</div>
          <div>
            <strong>{t("components.workspace.leftRail.account")}</strong>
            <span>{String(user?.email || t("components.workspace.leftRail.systemSettings"))}</span>
          </div>
        </button>
      </div>
    </aside>
  );
};

export default LeftExperimentRail;
