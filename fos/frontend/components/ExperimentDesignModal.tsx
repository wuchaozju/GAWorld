/**
 * This file shows the experiment designer as a popup layer.
 *
 * ExperimentDesignModal only decides when the popup is open and wraps
 * the shared design panel with the modal backdrop.
 */

import React from "react";

import { useSimulationStore } from "../store";
import { ExperimentDesignPanel } from "./experiment/ExperimentDesignPanel";

export const ExperimentDesignModal: React.FC = () => {
  const isOpen = useSimulationStore((state) => state.isExperimentDesignerOpen);
  const toggleExperimentDesigner = useSimulationStore(
    (state) => state.toggleExperimentDesigner
  );

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[140] flex items-center justify-center backdrop-blur-sm"
      style={{ background: "var(--ss-overlay)" }}
    >
      <ExperimentDesignPanel
        mode="modal"
        onClose={() => toggleExperimentDesigner(false)}
      />
    </div>
  );
};
