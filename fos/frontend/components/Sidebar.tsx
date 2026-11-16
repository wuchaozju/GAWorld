/**
 * This file shows the agents page inside the simulation workspace.
 *
 * Sidebar lets people switch between the agent watch list and the
 * network view without leaving the agents tab.
 */

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Network, Users } from "lucide-react";
import { useSimulationStore } from "../store";
import { AgentPanel } from "./AgentPanel";
import { SimulationNetworkPanel } from "./SimulationNetworkPanel";

type SidebarTab = "agent-watch" | "network";

export const Sidebar: React.FC = () => {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<SidebarTab>("agent-watch");
  const agents = useSimulationStore((state) => state.agents);

  return (
    <div
      className="h-full flex flex-col shadow-sm"
      style={{ background: "var(--ss-workspace-surface)" }}
    >
      <div
        className="flex border-b px-3 pt-3"
        style={{ borderColor: "var(--ss-workspace-border)" }}
      >
        <button
          type="button"
          onClick={() => setActiveTab("agent-watch")}
          className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 transition-colors ${
            activeTab === "agent-watch"
              ? "font-semibold"
              : "opacity-70 hover:opacity-100"
          }`}
          style={{
            borderColor:
              activeTab === "agent-watch"
                ? "var(--ss-brand-primary)"
                : "transparent",
            color:
              activeTab === "agent-watch"
                ? "var(--ss-brand-primary)"
                : "var(--ss-workspace-text)",
          }}
        >
          <Users size={16} />
          <span>{t("components.sidebar.agentWatch")}</span>
          <span
            className="text-xs px-2 py-0.5 rounded-full"
            style={{
              background: "var(--ss-brand-soft)",
              color: "var(--ss-brand-primary)",
            }}
          >
            {agents.length}
          </span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("network")}
          className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 transition-colors ${
            activeTab === "network"
              ? "font-semibold"
              : "opacity-70 hover:opacity-100"
          }`}
          style={{
            borderColor:
              activeTab === "network"
                ? "var(--ss-brand-primary)"
                : "transparent",
            color:
              activeTab === "network"
                ? "var(--ss-brand-primary)"
                : "var(--ss-workspace-text)",
          }}
        >
          <Network size={16} />
          <span>{t("simPage.network")}</span>
        </button>
      </div>

      <div className="flex-1 overflow-hidden relative">
        {activeTab === "agent-watch" ? <AgentPanel /> : <SimulationNetworkPanel />}
      </div>
    </div>
  );
};
