/**
 * This file tests which workspace overlays should mount.
 * test_get_workspace_overlay_mount_state_skips_closed_overlays checks hidden tools stay out of the page tree.
 * test_get_workspace_overlay_mount_state_keeps_open_overlays_ready checks only the open tools are marked to mount.
 */

import { describe, expect, it } from "vitest";

import { getWorkspaceOverlayMountState } from "./simulationPageRender";

describe("simulationPageRender", () => {
  it("test_get_workspace_overlay_mount_state_skips_closed_overlays", () => {
    const overlays = getWorkspaceOverlayMountState({
      isWizardOpen: false,
      isHelpModalOpen: false,
      isAnalyticsOpen: false,
      isExportOpen: false,
      isExperimentDesignerOpen: false,
      isTimeSettingsOpen: false,
      isSaveTemplateOpen: false,
      isNetworkEditorOpen: false,
      isReportModalOpen: false,
      globalKnowledgeOpen: false,
      isGuideOpen: false,
    });

    expect(Object.values(overlays).every((isMounted) => isMounted === false)).toBe(true);
  });

  it("test_get_workspace_overlay_mount_state_keeps_open_overlays_ready", () => {
    const overlays = getWorkspaceOverlayMountState({
      isWizardOpen: true,
      isHelpModalOpen: false,
      isAnalyticsOpen: true,
      isExportOpen: false,
      isExperimentDesignerOpen: true,
      isTimeSettingsOpen: false,
      isSaveTemplateOpen: false,
      isNetworkEditorOpen: true,
      isReportModalOpen: true,
      globalKnowledgeOpen: false,
      isGuideOpen: true,
    });

    expect(overlays.experimentBuilder).toBe(true);
    expect(overlays.analytics).toBe(true);
    expect(overlays.experimentDesigner).toBe(true);
    expect(overlays.networkEditor).toBe(true);
    expect(overlays.report).toBe(true);
    expect(overlays.guide).toBe(true);
    expect(overlays.export).toBe(false);
    expect(overlays.timeSettings).toBe(false);
  });
});
