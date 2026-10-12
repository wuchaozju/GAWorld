/**
 * This file decides which extra workspace panels should exist in the page tree.
 * getWorkspaceOverlayMountState marks each optional overlay as mounted or skipped.
 */

export interface WorkspaceOverlayInputs {
  isWizardOpen: boolean;
  isHelpModalOpen: boolean;
  isAnalyticsOpen: boolean;
  isExportOpen: boolean;
  isExperimentDesignerOpen: boolean;
  isTimeSettingsOpen: boolean;
  isSaveTemplateOpen: boolean;
  isNetworkEditorOpen: boolean;
  isReportModalOpen: boolean;
  globalKnowledgeOpen: boolean;
  isGuideOpen: boolean;
}

export interface WorkspaceOverlayMountState {
  experimentBuilder: boolean;
  help: boolean;
  analytics: boolean;
  export: boolean;
  experimentDesigner: boolean;
  timeSettings: boolean;
  templateSave: boolean;
  networkEditor: boolean;
  report: boolean;
  globalKnowledge: boolean;
  guide: boolean;
}

export function getWorkspaceOverlayMountState(
  overlays: WorkspaceOverlayInputs,
): WorkspaceOverlayMountState {
  return {
    experimentBuilder: overlays.isWizardOpen,
    help: overlays.isHelpModalOpen,
    analytics: overlays.isAnalyticsOpen,
    export: overlays.isExportOpen,
    experimentDesigner: overlays.isExperimentDesignerOpen,
    timeSettings: overlays.isTimeSettingsOpen,
    templateSave: overlays.isSaveTemplateOpen,
    networkEditor: overlays.isNetworkEditorOpen,
    report: overlays.isReportModalOpen,
    globalKnowledge: overlays.globalKnowledgeOpen,
    guide: overlays.isGuideOpen,
  };
}
