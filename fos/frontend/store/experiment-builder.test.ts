import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/scenarios', () => ({
  getAllScenarios: vi.fn(),
  getScenario: vi.fn(),
  getScenarioActions: vi.fn(),
  getScenarioDefaultAgents: vi.fn(() => Promise.resolve([
    {
      id: '34',
      name: 'Xu Guilan',
      profile: 'Age: 42',
      role_prompt: 'Real GAWorld profile',
      properties: {
        residence: 'Hangzhou',
      },
      llm_config: {},
    },
  ])),
}));

import { useExperimentBuilder } from './experiment-builder';


describe('Experiment Builder Store', () => {
  beforeEach(() => {
    useExperimentBuilder.getState().reset();
  });

  it('inherits sequential round visibility from scenario defaults', () => {
    useExperimentBuilder.getState().setSelectedScenarioData({
      id: 'policy_erosion',
      name: 'Policy Meaning Erosion',
      category: 'sociology',
      description: 'A hierarchy transmits a policy.',
      interaction_mode: 'sequential',
      parameters: [],
      actions: [],
    });

    expect(useExperimentBuilder.getState().roundVisibility).toBe('sequential');
  });

  it('keeps simultaneous round visibility for simultaneous scenarios', () => {
    useExperimentBuilder.getState().setSelectedScenarioData({
      id: 'social_norm_disruption',
      name: 'Social Norm Disruption',
      category: 'sociology',
      description: 'A new rule is imposed.',
      interaction_mode: 'simultaneous',
      parameters: [],
      actions: [],
    });

    expect(useExperimentBuilder.getState().roundVisibility).toBe('simultaneous');
  });

  it('starts custom scenario with sequential ordering for v1', () => {
    useExperimentBuilder.getState().setSelectedScenarioData({
      id: 'custom',
      name: 'Custom Scenario',
      category: 'custom',
      description: 'Open ended conversation.',
      interaction_mode: 'simultaneous',
      parameters: [],
      actions: [],
    });

    expect(useExperimentBuilder.getState().roundVisibility).toBe('sequential');
  });

  it('initializes standard scenario params from backend scenario defaults', () => {
    useExperimentBuilder.getState().setSelectedScenarioData({
      id: 'public_goods',
      name: 'Public Goods Game',
      category: 'game_theory',
      description: 'Agents allocate private resources to a shared pool.',
      interaction_mode: 'simultaneous',
      parameters: [
        { key: 'resource_name', label: 'Resource Name', type: 'string', default: 'tokens' },
        { key: 'tokens_per_round', label: 'Tokens Per Round', type: 'integer', default: 10 },
        { key: 'multiplier', label: 'Multiplier', type: 'number', default: 1.3 },
      ],
      actions: [],
    });

    expect(useExperimentBuilder.getState().scenarioParams).toEqual({
      resource_name: 'tokens',
      tokens_per_round: 10,
      multiplier: 1.3,
    });
  });

  it('leaves GAWorld params to the existing Step 2 profile initializer', () => {
    useExperimentBuilder.getState().setSelectedScenarioData({
      id: 'gaworld',
      name: 'GA World',
      category: 'spatial',
      description: 'A location-aware GAWorld scenario.',
      interaction_mode: 'simultaneous',
      parameters: [
        { key: 'execution_profile', label: 'Execution Profile', type: 'string', default: 'fast' },
      ],
      actions: [],
    });

    expect(useExperimentBuilder.getState().scenarioParams).toEqual({});
  });

  it('test_gaworld_selection_loads_profile_agents', async () => {
    await useExperimentBuilder.getState().loadDefaultAgentsForScenario('gaworld', '34');

    expect(useExperimentBuilder.getState().agentMode).toBe('manual');
    expect(useExperimentBuilder.getState().agentTypes).toEqual([
      {
        id: '34',
        label: 'Xu Guilan',
        count: 1,
        rolePrompt: 'Real GAWorld profile',
        userProfile: 'Age: 42',
        properties: {
          residence: 'Hangzhou',
        },
        providerId: null,
      },
    ]);
  });
});
