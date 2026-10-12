/**
 * This file shows the run controls used on the workspace page.
 *
 * `WorkspaceRunControls` shows run status, agent count, step progress,
 * and the advance controls.
 */

import React from "react";
import { useTranslation } from "react-i18next";
import { Play, Square } from "lucide-react";

import { useSimulationStore } from "../store";
import { Button } from "./ui/button";

interface WorkspaceRunControlsProps {
  progressLabel?: string | null;
  compact?: boolean;
}

// This shows the main workspace controls in a compact row.
export const WorkspaceRunControls: React.FC<WorkspaceRunControlsProps> = ({
  progressLabel,
  compact = false,
}) => {
  const { t } = useTranslation();
  const isGenerating = useSimulationStore((state) => state.isGenerating);
  const isAutoAdvancing = useSimulationStore((state) => state.isAutoAdvancing);
  const autoAdvanceCurrent = useSimulationStore((state) => state.autoAdvanceCurrent);
  const autoAdvanceTotal = useSimulationStore((state) => state.autoAdvanceTotal);
  const startAutoAdvance = useSimulationStore((state) => state.startAutoAdvance);
  const stopAutoAdvance = useSimulationStore((state) => state.stopAutoAdvance);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const isCompareMode = useSimulationStore((state) => state.isCompareMode);
  const agents = useSimulationStore((state) => state.agents);

  const [advanceSteps, setAdvanceSteps] = React.useState(1);
  const isRunning = isGenerating || isAutoAdvancing;
  const selectedNodeIsReady = String(selectedNodeId || "").trim().length > 0;
  const agentCount = agents.length;
  const formattedAgentCount = new Intl.NumberFormat().format(agentCount);

  return (
    <div className={`flex flex-wrap items-center justify-end gap-2 ${compact ? "w-full" : ""}`}>
      {isRunning ? (
        <div
          className="inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm"
          style={{
            background: "rgba(126, 164, 120, 0.10)",
            borderColor: "rgba(126, 164, 120, 0.24)",
            color: "#5F8F61",
          }}
        >
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-40" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-current" />
          </span>
          <span className="font-medium">{t("sim.running")}</span>
        </div>
      ) : null}

      {agentCount > 0 ? (
        <div
          className="inline-flex items-center rounded-full border px-3 py-2 text-sm font-medium"
          style={{
            background: "var(--ss-workspace-surface)",
            borderColor: "var(--ss-workspace-border)",
            color: "var(--ss-workspace-heading)",
          }}
        >
          {`${formattedAgentCount} ${t("sim.agents")}`}
        </div>
      ) : null}

      {progressLabel ? (
        <div
          className="inline-flex items-center rounded-full border px-3 py-2 text-sm font-medium"
          style={{
            background: "var(--ss-workspace-surface)",
            borderColor: "var(--ss-workspace-border)",
            color: "var(--ss-workspace-heading)",
          }}
        >
          {progressLabel}
        </div>
      ) : null}

      <div
        role="group"
        aria-label={t("simPage.advanceControls")}
        className="flex items-center gap-2 rounded-2xl border px-2 py-2 shadow-sm"
        style={{
          background: "var(--ss-workspace-surface)",
          borderColor: "var(--ss-workspace-border)",
        }}
      >
        <div
          className="flex items-center gap-2 rounded-xl border px-3 py-2"
          style={{
            background: "var(--ss-workspace-bg)",
            borderColor: "var(--ss-workspace-border)",
          }}
        >
          <input
            type="number"
            min={1}
            max={100}
            value={advanceSteps}
            onChange={(event) => {
              const nextValue = Number.parseInt(event.target.value, 10);
              if (Number.isNaN(nextValue)) {
                return;
              }

              setAdvanceSteps(Math.min(100, Math.max(1, nextValue)));
            }}
            disabled={isAutoAdvancing || isGenerating || isCompareMode}
            className="w-16 bg-transparent text-sm text-center focus:outline-none disabled:opacity-50"
            title={t("simPage.enterSteps")}
          />
          <span className="text-xs font-medium" style={{ color: "var(--ss-workspace-muted)" }}>
            steps
          </span>
        </div>

        {isAutoAdvancing ? (
          <Button
            variant="destructive"
            size="sm"
            onClick={() => stopAutoAdvance()}
            className="min-w-[132px]"
          >
            <Square size={14} />
            {t("simPage.stop")}
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={() => startAutoAdvance(advanceSteps)}
            disabled={isGenerating || isCompareMode || !selectedNodeIsReady}
            className={`min-w-[148px] ${isGenerating ? "!bg-[var(--ss-text-muted)] !text-[var(--ss-neutral-0)] !shadow-none" : ""}`}
          >
            <Play size={14} fill="currentColor" />
            {t("simPage.advance")}
          </Button>
        )}
      </div>

      {isAutoAdvancing ? (
        <span className="text-xs px-2" style={{ color: "var(--ss-text-muted)" }}>
          {t("simPage.advancingProgress", {
            current: autoAdvanceCurrent,
            total: autoAdvanceTotal,
          })}
        </span>
      ) : null}
    </div>
  );
};

export default WorkspaceRunControls;
