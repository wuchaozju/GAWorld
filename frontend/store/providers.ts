// frontend/store/providers.ts
//
// LLM provider management slice.
//
// Responsibilities:
//   - Manages list of configured LLM providers
//   - Tracks current active and selected provider
//   - Loads providers from backend API
//
// Used by: SettingsPage, SimulationWizard, any component that needs LLM access

import { StateCreator } from 'zustand';
import type { Provider as ServiceProvider } from '../services/providers';

export type Provider = ServiceProvider;

export interface ProvidersSlice {
  // State
  llmProviders: Provider[];
  currentProviderId: number | null;
  selectedProviderId: number | null;
  providersLoading: boolean;

  // Actions
  loadProviders: () => Promise<void>;
  setSelectedProvider: (id: number | null) => void;
}

export const createProvidersSlice: StateCreator<
  ProvidersSlice,
  [],
  [],
  ProvidersSlice
> = (set, get) => ({
  // Initial state
  llmProviders: [],
  providersLoading: false,
  currentProviderId: null,
  selectedProviderId: null,

  // Actions
  loadProviders: async () => {
    console.log('[loadProviders] Starting to load providers...');
    const { listProviders } = await import('../services/providers');
    set({ providersLoading: true });
    try {
      const providers = await listProviders();
      console.log('[loadProviders] Loaded providers:', providers);
      console.log('[loadProviders] Providers count:', providers?.length);
      const current =
        providers.find((p) => p.is_active || p.is_default) || providers[0] || null;

      set({
        llmProviders: providers,
        providersLoading: false,
        currentProviderId: current ? current.id : null,
        selectedProviderId: current ? current.id : null
      });
      console.log('[loadProviders] State updated successfully');
    } catch (e) {
      console.error("[loadProviders] Failed to load providers:", e);
      set({ providersLoading: false });
    }
  },

  setSelectedProvider: (id) => set({ selectedProviderId: id })
});
