// This file checks that creating connected experiments sends the right scene and agent details to the backend.
import { waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const simulationServiceMocks = vi.hoisted(() => ({
  createSimulation: vi.fn(),
  startSimulation: vi.fn(),
}));

vi.mock('../services/simulations', () => ({
  createSimulation: simulationServiceMocks.createSimulation,
  startSimulation: simulationServiceMocks.startSimulation,
}));

vi.mock('../services/simulationTree', () => ({
  getTreeGraph: vi.fn().mockResolvedValue({
    root: 0,
    frontier: [0],
    nodes: [{ id: 0, depth: 0 }],
    edges: [],
  }),
}));

import { useSimulationStore } from '../store';
import type { SimulationTemplate } from '../types';

describe('Simulation Slice - Connected Experiment Payload', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    simulationServiceMocks.createSimulation.mockResolvedValue({
      id: 'sim-connected',
      name: 'Connected Simulation',
    });
    simulationServiceMocks.startSimulation.mockResolvedValue({});
    useSimulationStore.setState({
      simulations: [],
      currentSimulation: null,
      nodes: [],
      selectedNodeId: null,
      agents: [],
      logs: [],
      rawEvents: [],
      notifications: [],
      engineConfig: {
        endpoint: '/api',
        status: 'disconnected',
        token: undefined,
      },
      selectedProviderId: null,
      currentProviderId: null,
    });
  });

  it('passes scenario_id and round_visibility at the top level of scene_config', async () => {
    const { createSimulation } = await import('../services/simulations');
    const template: SimulationTemplate = {
      id: 'experiment-template',
      name: 'Public Goods Test',
      description: 'Experiment',
      category: 'custom',
      sceneType: 'experiment',
      agents: [],
      defaultTimeConfig: {
        baseTime: new Date().toISOString(),
        unit: 'hour',
        step: 1,
      },
      genericConfig: {
        id: 'public-goods',
        name: 'Public Goods',
        description: 'Public goods experiment',
        coreMechanics: [],
        availableActions: [],
        scenario_id: 'public_goods',
        round_visibility: 'simultaneous',
        parameters: {
          initial_amount: 20,
          multiplier: 1.5,
        },
        actions: [
          {
            action_type: 'choice',
            name: 'Contribute',
            description: 'Contribute some tokens to the pool',
            parameters: [
              {
                name: 'amount',
                type: 'integer',
                description: 'How much to contribute',
                required: true,
                default: null,
              },
            ],
          },
        ],
        environment: {
          description: 'Public goods experiment',
        },
      },
      defaultNetwork: {},
    };

    useSimulationStore.getState().addSimulation(
      'Public Goods Test',
      template,
      undefined,
      undefined,
    );

    await waitFor(() => {
      expect(createSimulation).toHaveBeenCalledTimes(1);
    });
    const payload = vi.mocked(createSimulation).mock.calls[0][1];
    expect(payload.scene_type).toBe('experiment_template');
    expect(payload.scene_config.scenario_id).toBe('public_goods');
    expect(payload.scene_config.round_visibility).toBe('simultaneous');
    expect(payload.scene_config.parameters).toEqual({
      initial_amount: 20,
      multiplier: 1.5,
    });
    expect(payload.scene_config.actions).toEqual([
      {
        action_type: 'choice',
        name: 'Contribute',
        description: 'Contribute some tokens to the pool',
        parameters: [
          {
            name: 'amount',
            type: 'integer',
            description: 'How much to contribute',
            required: true,
            default: null,
          },
        ],
      },
    ]);
  });

  it('test_gaworld_launch_uses_gaworld_scene_type', async () => {
    const { createSimulation } = await import('../services/simulations');
    const template: SimulationTemplate = {
      id: 'experiment-template',
      name: 'GAWorld Test',
      description: 'Generative city experiment',
      category: 'custom',
      sceneType: 'experiment',
      agents: [
        {
          id: '34',
          name: 'Xu Guilan',
          role: 'Resident',
          avatarUrl: '',
          profile: 'Age: 42',
          llmConfig: {
            provider: 'mock',
            model: 'mock',
          },
          properties: { residence: 'Hangzhou' },
          history: {},
          memory: [],
          knowledgeBase: [],
        },
      ],
      defaultTimeConfig: {
        baseTime: new Date().toISOString(),
        unit: 'hour',
        step: 1,
      },
      genericConfig: {
        id: 'gaworld',
        name: 'GAWorld',
        description: 'Generative city experiment',
        coreMechanics: [],
        availableActions: [],
        scenario_id: 'gaworld',
        round_visibility: 'simultaneous',
        parameters: {
          sim_days: 2,
          agent_ids: '34',
        },
        actions: [
          {
            name: 'work',
            description: 'Work',
          },
        ],
        environment: {
          description: 'Generative city experiment',
        },
      },
      defaultNetwork: {},
    };

    useSimulationStore.getState().addSimulation(
      'GAWorld Test',
      template,
      undefined,
      undefined,
    );

    await waitFor(() => {
      expect(createSimulation).toHaveBeenCalledTimes(1);
    });
    const payload = vi.mocked(createSimulation).mock.calls[0][1];
    expect(payload.scene_type).toBe('gaworld_scene');
    expect(payload.scene_config.parameters).toEqual({
      sim_days: 2,
      agent_ids: '34',
    });
    expect(payload.agent_config.agents).toHaveLength(1);
  });

  it('keeps selected gaworld agent ids and infers agent_ids when the text field is blank', async () => {
    const { createSimulation } = await import('../services/simulations');
    const template: SimulationTemplate = {
      id: 'experiment-template',
      name: 'GAWorld Selected Agents',
      description: 'Generative city experiment',
      category: 'custom',
      sceneType: 'experiment',
      agents: [
        {
          id: '1',
          name: 'Li Zeyu',
          role: 'Resident',
          avatarUrl: '',
          profile: 'Age: 24',
          llmConfig: {
            provider: 'mock',
            model: 'mock',
          },
          properties: { residence: 'Hangzhou' },
          history: {},
          memory: [],
          knowledgeBase: [],
        },
        {
          id: '2',
          name: 'Zhou Wanqing',
          role: 'Resident',
          avatarUrl: '',
          profile: 'Age: 26',
          llmConfig: {
            provider: 'mock',
            model: 'mock',
          },
          properties: { residence: 'Hangzhou' },
          history: {},
          memory: [],
          knowledgeBase: [],
        },
        {
          id: '3',
          name: 'Chen Yihang',
          role: 'Resident',
          avatarUrl: '',
          profile: 'Age: 22',
          llmConfig: {
            provider: 'mock',
            model: 'mock',
          },
          properties: { residence: 'Hangzhou' },
          history: {},
          memory: [],
          knowledgeBase: [],
        },
        {
          id: '4',
          name: 'Xu Manting',
          role: 'Resident',
          avatarUrl: '',
          profile: 'Age: 28',
          llmConfig: {
            provider: 'mock',
            model: 'mock',
          },
          properties: { residence: 'Hangzhou' },
          history: {},
          memory: [],
          knowledgeBase: [],
        },
      ],
      defaultTimeConfig: {
        baseTime: new Date().toISOString(),
        unit: 'hour',
        step: 1,
      },
      genericConfig: {
        id: 'gaworld',
        name: 'GAWorld',
        description: 'Generative city experiment',
        coreMechanics: [],
        availableActions: [],
        scenario_id: 'gaworld',
        round_visibility: 'simultaneous',
        parameters: {
          sim_days: 2,
          agent_ids: '',
        },
        actions: [
          {
            name: 'work',
            description: 'Work',
          },
        ],
        environment: {
          description: 'Generative city experiment',
        },
      },
      defaultNetwork: {},
    };

    useSimulationStore.getState().addSimulation(
      'GAWorld Selected Agents',
      template,
      undefined,
      undefined,
    );

    await waitFor(() => {
      expect(createSimulation).toHaveBeenCalledTimes(1);
    });
    const payload = vi.mocked(createSimulation).mock.calls[0][1];
    expect(payload.scene_type).toBe('gaworld_scene');
    expect(payload.scene_config.parameters.agent_ids).toBe('1,2,3,4');
    expect(payload.agent_config.agents.map((agent: { id: string }) => agent.id)).toEqual([
      '1',
      '2',
      '3',
      '4',
    ]);
  });
});
