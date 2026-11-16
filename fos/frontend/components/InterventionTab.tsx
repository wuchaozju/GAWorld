/**
 * This file shows the intervention area inside the simulation page.
 *
 * InterventionTab lets people switch between host control and
 * experiment design from one place.
 */

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Beaker, Zap } from "lucide-react";

import { HostPanel } from "./HostPanel";
import { ExperimentDesignPanel } from "./experiment/ExperimentDesignPanel";

type InterventionView = "host-control" | "design-experiment";

export const InterventionTab: React.FC = () => {
  const { t } = useTranslation();
  const [activeView, setActiveView] = useState<InterventionView>("design-experiment");

  return (
    <div
      className="h-full flex flex-col"
      style={{ background: "var(--ss-workspace-bg)" }}
    >
      <div
        className="flex items-center gap-2 border-b px-5 pt-4"
        style={{ borderColor: "var(--ss-workspace-border)" }}
      >
        <button
          type="button"
          onClick={() => setActiveView("design-experiment")}
          className="flex items-center gap-2 px-4 py-2 text-sm border-b-2"
          style={{
            borderColor:
              activeView === "design-experiment"
                ? "var(--ss-brand-primary)"
                : "transparent",
            color:
              activeView === "design-experiment"
                ? "var(--ss-brand-primary)"
                : "var(--ss-workspace-text)",
          }}
        >
          <Beaker size={16} />
          {t("simPage.designExperiment")}
        </button>
        <button
          type="button"
          onClick={() => setActiveView("host-control")}
          className="flex items-center gap-2 px-4 py-2 text-sm border-b-2"
          style={{
            borderColor:
              activeView === "host-control"
                ? "var(--ss-brand-primary)"
                : "transparent",
            color:
              activeView === "host-control"
                ? "var(--ss-brand-primary)"
                : "var(--ss-workspace-text)",
          }}
        >
          <Zap size={16} />
          {t("components.interventionTab.hostControl")}
        </button>
      </div>

      <div className="flex-1 overflow-hidden">
        {activeView === "host-control" ? <HostPanel /> : <ExperimentDesignPanel onClose={() => setActiveView("host-control")} />}
      </div>
    </div>
  );
};
