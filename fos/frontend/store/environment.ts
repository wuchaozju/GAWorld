// frontend/store/environment.ts
//
// Environment suggestions and host actions slice.
//
// Responsibilities:
//   - Manages dynamic environment event suggestions
//   - Environment suggestion generation and application
//   - Host intervention actions (inject logs)
//
// Used by: EnvironmentSuggestion, SimulationPage, host controls

import { StateCreator } from 'zustand';
import type { EnvironmentSuggestion } from '../services/environmentSuggestions';
import type { LogEntry, Agent } from '../types';

export interface EnvironmentSlice {
  // State
  environmentEnabled: boolean;
  environmentSuggestionsAvailable: boolean;
  environmentSuggestions: EnvironmentSuggestion[];
  environmentSuggestionsLoading: boolean;

  // Actions
  checkEnvironmentSuggestions: () => Promise<void>;
  generateEnvironmentSuggestions: () => Promise<void>;
  applyEnvironmentSuggestion: (suggestion: EnvironmentSuggestion) => Promise<void>;
  dismissEnvironmentSuggestions: () => void;
  toggleEnvironmentEnabled: () => Promise<void>;
}

export const createEnvironmentSlice: StateCreator<
  EnvironmentSlice,
  [],
  [],
  EnvironmentSlice
> = (set, get) => ({
  // Initial state
  environmentEnabled: false,
  environmentSuggestionsAvailable: false,
  environmentSuggestions: [],
  environmentSuggestionsLoading: false,

  // Actions
  checkEnvironmentSuggestions: async () => {
    const currentSimulation = (get() as any).currentSimulation;
    if (!currentSimulation?.id) return;

    try {
      const { getSuggestionStatus } = await import('../services/environmentSuggestions');
      const selectedNodeId = (get() as any).selectedNodeId;
      const status = await getSuggestionStatus(currentSimulation.id, selectedNodeId);

      set({
        environmentSuggestionsAvailable: status.available || false,
        environmentEnabled: status.enabled || false
      });
    } catch (e) {
      console.warn('Failed to check environment suggestions', e);
    }
  },

  generateEnvironmentSuggestions: async () => {
    const currentSimulation = (get() as any).currentSimulation;
    if (!currentSimulation?.id) return;

    set({ environmentSuggestionsLoading: true });

    try {
      const { generateSuggestions } = await import('../services/environmentSuggestions');
      const selectedNodeId = (get() as any).selectedNodeId;
      const result = await generateSuggestions(currentSimulation.id, selectedNodeId);

      set({
        environmentSuggestions: result.suggestions || [],
        environmentSuggestionsAvailable: false,
        environmentSuggestionsLoading: false
      });
    } catch (e) {
      console.error('Failed to generate environment suggestions', e);
      set({ environmentSuggestionsLoading: false });
      const addNotification = (get() as any).addNotification;
      addNotification?.('error', '生成环境事件建议失败');
    }
  },

  applyEnvironmentSuggestion: async (suggestion) => {
    const currentSimulation = (get() as any).currentSimulation;
    if (!currentSimulation?.id) return;

    try {
      const { applyEnvironmentEvent } = await import('../services/environmentSuggestions');
      const selectedNodeId = (get() as any).selectedNodeId;
      await applyEnvironmentEvent(currentSimulation.id, {
        ...suggestion,
        node_id: selectedNodeId,
      });

      // Inject as a log entry
      const injectLog = (get() as any).injectLog;
      if (selectedNodeId && injectLog) {
        injectLog(
          'ENVIRONMENT',
          `[环境事件] ${suggestion.description}`
        );
      }

      set({ environmentSuggestions: [] });
      const addNotification = (get() as any).addNotification;
      addNotification?.('success', '环境事件已应用');
    } catch (e) {
      console.error('Failed to apply environment suggestion', e);
      const addNotification = (get() as any).addNotification;
      addNotification?.('error', '应用环境事件失败');
    }
  },

  dismissEnvironmentSuggestions: () => {
    set({ environmentSuggestions: [] });
  },

  toggleEnvironmentEnabled: async () => {
    const currentSimulation = (get() as any).currentSimulation;
    if (!currentSimulation?.id) return;

    const newState = !get().environmentEnabled;

    try {
      const { apiClient } = await import('../services/client');
      await apiClient.patch(`simulations/${currentSimulation.id}`, {
        scene_config: { environment_enabled: newState }
      });

      set({ environmentEnabled: newState });
      const addNotification = (get() as any).addNotification;
      addNotification?.('success', newState ? '环境事件已启用' : '环境事件已禁用');
    } catch (e) {
      console.error('Failed to toggle environment', e);
      const addNotification = (get() as any).addNotification;
      addNotification?.('error', '切换环境事件状态失败');
    }
  }
});
