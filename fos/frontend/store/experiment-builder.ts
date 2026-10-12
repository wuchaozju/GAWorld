/**
 * Experiment Builder State Management
 *
 * Manages the state for the 5-step Experiment Builder UI.
 * Provides actions for updating configuration and validation.
 */

import { create } from 'zustand';
import { v4 as uuidv4 } from 'uuid';
import type { SocialNetwork } from '../types';
import {
  ScenarioData,
  ScenarioParam,
  ActionDef,
  getAllScenarios,
  getScenario,
  getScenarioActions,
  getScenarioDefaultAgents,
} from '../services/scenarios';

export interface LLMProvider {
  id: number;
  name: string;
  provider: string;
  model?: string;
  base_url?: string;
  is_active?: boolean;
  is_default?: boolean;
}

export interface ManualAgentType {
  id: string;
  label: string;
  count: number;
  rolePrompt: string;
  userProfile: string;
  properties: Record<string, unknown>;
  providerId?: number | null;
}

interface DefaultScenarioAgent {
  id?: unknown;
  name?: unknown;
  profile?: unknown;
  user_profile?: unknown;
  role_prompt?: unknown;
  rolePrompt?: unknown;
  properties?: unknown;
  provider_id?: unknown;
  providerId?: unknown;
}

export interface ExperimentBuilderState {
  // Current step
  currentStep: 1 | 2 | 3 | 4 | 5 | 6;
  completedSteps: Set<1 | 2 | 3 | 4 | 5 | 6>;

  // Step 1: Scenario selection
  selectedScenarioId: string | null;
  selectedScenarioData: ScenarioData | null;
  interactionTypes?: string[];
  scenario?: string;

  // Step 2: Scenario configuration
  scenarioDescription: string;
  scenarioParams: Record<string, unknown>;
  roundVisibility: 'simultaneous' | 'sequential' | 'random';
  turnOrder: 'fixed' | 'random';
  successCondition?: { type: string; maxRounds?: number };
  interRoundUpdate?: { type: string };
  metrics?: string[];
  networkType?: string;
  mechanicConfigs?: Record<string, unknown>;

  // Step 3: Actions
  availableActions: ActionDef[];
  selectedActionIds: string[];

  // Step 4: Agents
  agentMode: 'manual' | 'demographic' | 'import';
  agentTypes: ManualAgentType[];
  llmProviders: LLMProvider[];
  selectedProviderId: number | null;

  // Step 5: Network Configuration
  socialNetwork: SocialNetwork;

  // Validation
  validationErrors: Record<string, string>;
}

interface ExperimentBuilderActions {
  // Navigation
  setCurrentStep: (step: 1 | 2 | 3 | 4 | 5 | 6) => void;
  nextStep: () => void;
  prevStep: () => void;
  markStepComplete: (step: 1 | 2 | 3 | 4 | 5 | 6) => void;

  // Step 1: Scenario selection
  setSelectedScenarioId: (id: string | null) => void;
  setSelectedScenarioData: (data: ScenarioData | null) => void;

  // Step 2: Scenario configuration
  setScenarioDescription: (description: string) => void;
  setScenarioParams: (params: Record<string, unknown>) => void;
  setRoundVisibility: (visibility: 'simultaneous' | 'sequential' | 'random') => void;
  setTurnOrder: (order: 'fixed' | 'random') => void;

  // Step 3: Actions
  setAvailableActions: (actions: ActionDef[]) => void;
  setSelectedActionIds: (ids: string[]) => void;
  toggleActionId: (id: string) => void;

  // Step 4: Agents
  setAgentMode: (mode: 'manual' | 'demographic' | 'import') => void;
  addAgentType: (agentType: ManualAgentType) => void;
  removeAgentType: (id: string) => void;
  updateAgentType: (id: string, updates: Partial<ManualAgentType>) => void;
  loadDefaultAgentsForScenario: (scenarioId: string, agentIds?: string) => Promise<void>;
  loadProviders: () => Promise<void>;
  setSelectedProviderId: (id: number | null) => void;
  getSelectedProviderId: () => number | null;

  // Step 5: Network Configuration
  setSocialNetwork: (network: SocialNetwork) => void;

  // Validation
  validate: () => boolean;
  clearValidationErrors: () => void;

  // Reset
  reset: () => void;
}

const getInitialState = (): ExperimentBuilderState => ({
  currentStep: 1,
  completedSteps: new Set(),
  selectedScenarioId: null,
  selectedScenarioData: null,
  scenarioDescription: '',
  scenarioParams: {},
  roundVisibility: 'simultaneous',
  turnOrder: 'fixed',
  availableActions: [],
  selectedActionIds: [],
  agentMode: 'manual',
  agentTypes: [],
  llmProviders: [],
  selectedProviderId: null,
  socialNetwork: {},
  validationErrors: {},
  interactionTypes: [],
  scenario: '',
  successCondition: { type: 'fixed_rounds' },
  interRoundUpdate: { type: 'none' },
  metrics: [],
  networkType: 'custom',
  mechanicConfigs: {},
});

const initialState: ExperimentBuilderState = getInitialState();

const isPlainRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
);

const normalizeDefaultAgent = (agent: DefaultScenarioAgent): ManualAgentType => {
  const properties = isPlainRecord(agent.properties) ? { ...agent.properties } : {};
  const id = String(agent.id || uuidv4());
  const label = String(agent.name || id);
  const rolePrompt = String(agent.role_prompt || agent.rolePrompt || agent.profile || '');
  const userProfile = String(agent.profile || agent.user_profile || '');
  const providerIdValue = agent.provider_id ?? agent.providerId;
  const providerId = typeof providerIdValue === 'number' ? providerIdValue : null;

  return {
    id,
    label,
    count: 1,
    rolePrompt,
    userProfile,
    properties,
    providerId,
  };
};

const buildScenarioDefaultParams = (scenario: ScenarioData | null): Record<string, unknown> => {
  if (!scenario || scenario.id === 'gaworld') {
    return {};
  }

  return (scenario.parameters || []).reduce<Record<string, unknown>>((params, param) => {
    params[param.key] = param.default;
    return params;
  }, {});
};

export const STEPS = [
  { id: 1, title: 'Choose Scenario', description: 'Pick a preset or start blank' },
    { id: 2, title: 'Configure Scenario', description: 'Set description and parameters' },
    { id: 3, title: 'Select Actions', description: 'Choose what agents can do' },
    { id: 4, title: 'Create Agents', description: 'Define who participates' },
    { id: 5, title: 'Network', description: 'Configure social connections' },
    { id: 6, title: 'Review', description: 'Preview what agents will see' },
];

export const useExperimentBuilder = create<ExperimentBuilderState & ExperimentBuilderActions>((set, get) => ({
  ...initialState,

  // Navigation
  setCurrentStep: (step) => set({ currentStep: step }),

  nextStep: () => {
    const current = get().currentStep;
    if (current < 6) {
      set({ currentStep: (current + 1) as 1 | 2 | 3 | 4 | 5 | 6 });
    }
  },

  prevStep: () => {
    const current = get().currentStep;
    if (current > 1) {
      set({ currentStep: (current - 1) as 1 | 2 | 3 | 4 | 5 | 6 });
    }
  },

  markStepComplete: (step) => {
    const completed = new Set(get().completedSteps);
    completed.add(step);
    set({ completedSteps: completed });
  },

  // Step 1: Scenario selection
  setSelectedScenarioId: (id) => set((state) => {
    // Clear scenario error if now valid
    const newErrors = { ...state.validationErrors };
    if (id && newErrors.scenario) {
      delete newErrors.scenario;
    }
    return { selectedScenarioId: id, validationErrors: newErrors };
  }),

  setSelectedScenarioData: (data) => set((state) => ({
    selectedScenarioData: data,
    roundVisibility: data?.id === 'custom'
      ? 'sequential'
      : data?.interaction_mode === 'sequential'
        ? 'sequential'
        : 'simultaneous',
    turnOrder: data?.interaction_mode === 'sequential' ? state.turnOrder : 'fixed',
    scenarioDescription: '',
    scenarioParams: buildScenarioDefaultParams(data),
  })),

  // Step 2: Scenario configuration
  setScenarioDescription: (description) => set((state) => {
    // Clear description error if now valid
    const newErrors = { ...state.validationErrors };
    if (description.trim() && newErrors.description) {
      delete newErrors.description;
    }
    return { scenarioDescription: description, validationErrors: newErrors };
  }),

  setScenarioParams: (params) => set({ scenarioParams: params }),

  setRoundVisibility: (visibility) => set({ roundVisibility: visibility }),

  setTurnOrder: (order) => set({ turnOrder: order }),

  // Step 3: Actions
  setAvailableActions: (actions) => set({ availableActions: actions }),

  setSelectedActionIds: (ids) => set((state) => {
    // Clear actions error if now valid
    const newErrors = { ...state.validationErrors };
    if (ids.length > 0 && newErrors.actions) {
      delete newErrors.actions;
    }
    return { selectedActionIds: ids, validationErrors: newErrors };
  }),

  toggleActionId: (id) => {
    const current = get().selectedActionIds;
    if (current.includes(id)) {
      set({ selectedActionIds: current.filter((t) => t !== id) });
    } else {
      set({ selectedActionIds: [...current, id] });
    }
  },

  // Step 4: Agents
  setAgentMode: (mode) => set({ agentMode: mode }),

  addAgentType: (agentType) => {
    const types = [...get().agentTypes];
    types.push({ ...agentType, id: agentType.id || uuidv4() });
    set((state) => {
      // Clear agents error if now valid
      const newErrors = { ...state.validationErrors };
      const totalAgents = types.reduce((sum, t) => sum + (t.count || 0), 0);
      if (totalAgents > 0 && newErrors.agents) {
        delete newErrors.agents;
      }
      return { agentTypes: types, validationErrors: newErrors };
    });
  },

  removeAgentType: (id) => {
    set((state) => {
      const types = state.agentTypes.filter((t) => t.id !== id);
      const newErrors = { ...state.validationErrors };
      // Don't clear agents error on remove - only check on add
      return { agentTypes: types, validationErrors: newErrors };
    });
  },

  updateAgentType: (id, updates) => {
    set((state) => {
      const types = state.agentTypes.map((t) =>
        t.id === id ? { ...t, ...updates } : t
      );
      // Clear agents error if now valid
      const newErrors = { ...state.validationErrors };
      const totalAgents = types.reduce((sum, t) => sum + (t.count || 0), 0);
      if (totalAgents > 0 && newErrors.agents) {
        delete newErrors.agents;
      }
      return { agentTypes: types, validationErrors: newErrors };
    });
  },

  loadDefaultAgentsForScenario: async (scenarioId, agentIds) => {
    if (scenarioId !== 'gaworld') {
      return;
    }

    const defaultAgents = await getScenarioDefaultAgents(scenarioId, agentIds);
    const agentTypes = defaultAgents.map((agent) => normalizeDefaultAgent(agent));

    set((state) => {
      const newErrors = { ...state.validationErrors };
      if (agentTypes.length > 0 && newErrors.agents) {
        delete newErrors.agents;
      }
      return {
        agentMode: 'manual',
        agentTypes,
        validationErrors: newErrors,
      };
    });
  },

  loadProviders: async () => {
    const { apiClient } = await import('../services/client');
    try {
      // apiClient.get returns { data: T } where T is the generic type
      const { data } = await apiClient.get<LLMProvider[]>('/providers');
      set({ llmProviders: data });
      // Set default provider if none selected
      if (!get().selectedProviderId) {
        const active = data.find((p: LLMProvider) => p.is_active);
        if (active) set({ selectedProviderId: active.id });
      }
    } catch (error) {
      console.error('Failed to load providers:', error);
    }
  },

  setSelectedProviderId: (id) => set({ selectedProviderId: id }),

  getSelectedProviderId: () => get().selectedProviderId,

  // Step 5: Network Configuration
  setSocialNetwork: (network) => set({ socialNetwork: network }),

  // Validation
  validate: () => {
    const state = get();
    const errors: Record<string, string> = {};

    // Step 1: Scenario selected
    if (!state.selectedScenarioId) {
      errors['scenario'] = 'Please select a scenario';
    }

    // Step 2: Description not empty
    if (!state.scenarioDescription?.trim()) {
      errors['description'] = 'Please provide a scenario description';
    }

    // Step 3: At least 1 action selected
    if (state.selectedActionIds.length === 0) {
      errors['actions'] = 'Please select at least one action';
    }

    // Step 4: At least 1 agent
    const totalAgents = state.agentTypes.reduce((sum, type) => sum + (type.count || 0), 0);
    if (totalAgents === 0) {
      errors['agents'] = 'Please add at least one agent';
    }

    set({ validationErrors: errors });
    return Object.keys(errors).length === 0;
  },

  clearValidationErrors: () => set({ validationErrors: {} }),

  // Reset - use function to create fresh state each time
  reset: () => set(getInitialState()),
}));
