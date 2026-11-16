/**
 * This file shows the small left rail used to move between the main
 * simulation work areas.
 *
 * TabRail shows the main page buttons, keeps their labels visible, and
 * lets people widen or shrink the rail by dragging its edge.
 */

import React from "react";
import { useTranslation } from "react-i18next";
import { BarChart3, GitBranch, Users, Zap } from "lucide-react";
import { useSimulationStore } from "../store";
import { WorkspaceMoreActionsButton } from "./WorkspaceMoreActionsButton";

const TAB_ITEMS = [
  { key: "workspace", icon: GitBranch, tooltipKey: "simPage.tabs.workspace" },
  { key: "agents", icon: Users, tooltipKey: "simPage.tabs.agents" },
  { key: "intervention", icon: Zap, tooltipKey: "simPage.tabs.intervention" },
  { key: "analyse", icon: BarChart3, tooltipKey: "simPage.tabs.analyse" },
] as const;

const PEEK_DELAY_MS = 300;
const PEEK_DISMISS_DELAY_MS = 120;

interface TabRailProps {
  width: number;
}

export const TabRail: React.FC<TabRailProps> = ({ width }) => {
  const { t } = useTranslation();
  const activeTab = useSimulationStore((state) => state.activeTab);
  const setActiveTab = useSimulationStore((state) => state.setActiveTab);
  const setPeekTab = useSimulationStore((state) => state.setPeekTab);
  const hoverTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const dismissTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const canPeekTab = (tab: (typeof TAB_ITEMS)[number]["key"]) =>
    tab === "workspace" || tab === "agents";

  const handleMouseEnter = (tab: (typeof TAB_ITEMS)[number]["key"]) => {
    if (dismissTimerRef.current) {
      clearTimeout(dismissTimerRef.current);
      dismissTimerRef.current = null;
    }

    if (!canPeekTab(tab) || tab === activeTab) {
      return;
    }

    hoverTimerRef.current = setTimeout(() => {
      setPeekTab(tab);
    }, PEEK_DELAY_MS);
  };

  const handleMouseLeave = () => {
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }

    dismissTimerRef.current = setTimeout(() => {
      if (!useSimulationStore.getState().peekOverlayActive) {
        setPeekTab(null);
      }
    }, PEEK_DISMISS_DELAY_MS);
  };

  const handleClick = (tab: (typeof TAB_ITEMS)[number]["key"]) => {
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    if (dismissTimerRef.current) {
      clearTimeout(dismissTimerRef.current);
      dismissTimerRef.current = null;
    }

    setPeekTab(null);
    setActiveTab(tab);
  };

  return (
    <div
      className="flex flex-col items-stretch py-3 gap-2 border-r"
      style={{
        width,
        minWidth: width,
        background: "var(--ss-workspace-surface)",
        borderColor: "var(--ss-workspace-border)",
      }}
    >
      {TAB_ITEMS.map(({ key, icon: Icon, tooltipKey }) => {
        const isActive = activeTab === key;

        return (
          <button
            key={key}
            onClick={() => handleClick(key)}
            onMouseEnter={() => handleMouseEnter(key)}
            onMouseLeave={handleMouseLeave}
            title={t(tooltipKey)}
            className={`mx-2 flex flex-col items-center justify-center rounded-xl px-2 py-3 transition-colors ${
              isActive ? "" : "hover:bg-black/5"
            }`}
            style={{
              minHeight: 68,
              background: isActive ? "var(--ss-brand-soft)" : "transparent",
              color: isActive
                ? "var(--ss-brand-primary)"
                : "var(--ss-workspace-muted)",
            }}
          >
            <Icon size={20} strokeWidth={isActive ? 2.2 : 1.6} />
            <span className="mt-2 text-xs font-medium text-center leading-tight">
              {t(tooltipKey)}
            </span>
          </button>
        );
      })}

      <WorkspaceMoreActionsButton
        wrapperClassName="relative mx-2"
        triggerClassName="w-full min-h-[68px] rounded-xl px-2 py-3 text-[var(--ss-workspace-muted)] hover:bg-black/5 !flex-col gap-2"
        triggerLabel={t("simPage.more")}
        panelClassName="absolute left-full ml-3 bottom-0 w-72 rounded-2xl border shadow-xl p-3 z-20"
      />
    </div>
  );
};
