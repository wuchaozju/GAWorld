/**
 * These tests check advancing when the workspace still has the root placeholder.
 *
 * They make sure the store resolves the real backend root node before advancing.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const treeMocks = vi.hoisted(() => ({
  getTreeGraph: vi.fn(),
  treeAdvanceChain: vi.fn(),
  getSimEvents: vi.fn(),
  getSimState: vi.fn(),
}));

vi.mock('../../services/simulationTree', () => ({
  getTreeGraph: treeMocks.getTreeGraph,
  treeAdvanceChain: treeMocks.treeAdvanceChain,
  getSimEvents: treeMocks.getSimEvents,
  getSimState: treeMocks.getSimState,
}));

const experimentsMocks = vi.hoisted(() => ({
  createExperiment: vi.fn(),
  getExperiment: vi.fn(),
  listExperiments: vi.fn(),
  runExperiment: vi.fn(),
}));

vi.mock('../../services/experiments', () => ({
  createExperiment: experimentsMocks.createExperiment,
  getExperiment: experimentsMocks.getExperiment,
  listExperiments: experimentsMocks.listExperiments,
  runExperiment: experimentsMocks.runExperiment,
}));

import { useSimulationStore } from '../index';
import { useExperimentBuilder } from '../experiment-builder';

describe('advanceSimulation root placeholder handling', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    treeMocks.getTreeGraph.mockResolvedValue({
      root: 0,
      frontier: [0],
      nodes: [{ id: 0, depth: 0 }, { id: 1, depth: 1 }],
      edges: [{ from: 0, to: 1, type: 'advance' }],
      running: [],
    });
    treeMocks.treeAdvanceChain.mockResolvedValue({ child: 1 });
    treeMocks.getSimEvents.mockResolvedValue([]);
    treeMocks.getSimState.mockResolvedValue({
      turns: 1,
      agents: [],
      scene_config: {},
    });
    experimentsMocks.createExperiment.mockResolvedValue({
      experiment_id: 'exp-1',
      node_mapping: [{ node_id: 5, variant_id: 'v1', variant_name: 'A' }],
    });
    useExperimentBuilder.setState({
      llmProviders: [],
      selectedProviderId: null,
      agentTypes: [],
      failurePolicy: 'pause_and_ask',
      fallbackProviderIds: [],
    });

    useSimulationStore.setState({
      currentSimulation: { id: 'policy-sim-1', scene_type: 'policy_cascade_scene' },
      selectedNodeId: 'root',
      nodes: [{ id: 'root', parentId: null, name: 'Root', depth: 0, isLeaf: true }],
      agents: [],
      logs: [],
      rawEvents: [],
      isGenerating: false,
      isCompareMode: false,
      engineConfig: {
        endpoint: '/api',
        status: 'disconnected',
        token: undefined,
      },
      addNotification: vi.fn(),
    } as never);
  });

  it('advances from the backend root when the selected node is the root placeholder', async () => {
    await useSimulationStore.getState().advanceSimulation();

    expect(treeMocks.treeAdvanceChain).toHaveBeenCalledWith(
      '/api',
      'policy-sim-1',
      0,
      1,
      undefined,
    );
    expect(useSimulationStore.getState().selectedNodeId).toBe('1');
  });

  it('waits for the backend root when the first graph lookup is still loading', async () => {
    treeMocks.getTreeGraph
      .mockResolvedValueOnce(null)
      .mockResolvedValue({
        root: 0,
        frontier: [0],
        nodes: [{ id: 0, depth: 0 }, { id: 1, depth: 1 }],
        edges: [{ from: 0, to: 1, type: 'advance' }],
        running: [],
      });

    await useSimulationStore.getState().advanceSimulation();

    expect(treeMocks.getTreeGraph).toHaveBeenCalledTimes(3);
    expect(treeMocks.treeAdvanceChain).toHaveBeenCalledWith(
      '/api',
      'policy-sim-1',
      0,
      1,
      undefined,
    );
    expect(useSimulationStore.getState().selectedNodeId).toBe('1');
  });

  it('keeps waiting when the backend root takes longer to appear', async () => {
    vi.useFakeTimers();
    treeMocks.getTreeGraph
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValue({
        root: 0,
        frontier: [0],
        nodes: [{ id: 0, depth: 0 }, { id: 1, depth: 1 }],
        edges: [{ from: 0, to: 1, type: 'advance' }],
        running: [],
      });

    const advancePromise = useSimulationStore.getState().advanceSimulation();
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await vi.advanceTimersByTimeAsync(500);
    }
    await advancePromise;
    vi.useRealTimers();

    expect(treeMocks.treeAdvanceChain).toHaveBeenCalledWith(
      '/api',
      'policy-sim-1',
      0,
      1,
      undefined,
    );
    expect(useSimulationStore.getState().selectedNodeId).toBe('1');
  });
});

describe('runExperiment llm routing payload wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    experimentsMocks.createExperiment.mockResolvedValue({
      experiment_id: 'exp-1',
      node_mapping: [{ node_id: 5, variant_id: 'v1', variant_name: 'A' }],
    });
    treeMocks.getTreeGraph.mockResolvedValue({
      root: 0,
      frontier: [0],
      nodes: [{ id: 0, depth: 0 }, { id: 5, depth: 1 }],
      edges: [{ from: 0, to: 5, type: 'branch' }],
      running: [],
    });
    useSimulationStore.setState({
      currentSimulation: { id: 'policy-sim-1', scene_type: 'policy_cascade_scene' },
      selectedNodeId: '2',
      nodes: [
        { id: '2', parentId: null, name: 'Base', depth: 0, isLeaf: true },
      ],
      agents: [],
      logs: [],
      rawEvents: [],
      isGenerating: false,
      isCompareMode: false,
      engineConfig: { endpoint: '/api', status: 'disconnected', token: undefined },
      addNotification: vi.fn(),
    } as never);
  });

  it('sends the llm block built from builder state with exact agent-ID keys and policy', async () => {
    useExperimentBuilder.setState({
      llmProviders: [
        { id: 1, name: 'Default', provider: 'qwen-local', model: 'Qwen3-4B' },
        { id: 2, name: 'Other', provider: 'ministral', model: 'Ministral-3B' },
      ],
      selectedProviderId: 1,
      agentTypes: [
        {
          id: 'a1', label: 'Resident', count: 1, rolePrompt: '', userProfile: '',
          properties: { gaworld_agent_id: 7 }, providerId: 2,
        },
        {
          id: 'a2', label: 'Other', count: 1, rolePrompt: '', userProfile: '',
          properties: { gaworld_agent_id: 11 }, providerId: 1,
        },
        {
          id: 'a3', label: 'NoGid', count: 1, rolePrompt: '', userProfile: '',
          properties: {}, providerId: 2,
        },
      ],
      failurePolicy: 'ordered_fallback',
      fallbackProviderIds: [2],
    });

    useSimulationStore.getState().runExperiment('2', 'Routing experiment', [
      { name: 'A', ops: [] },
    ] as never);
    await new Promise((r) => setTimeout(r, 0));

    expect(experimentsMocks.createExperiment).toHaveBeenCalledTimes(1);
    const llm = experimentsMocks.createExperiment.mock.calls[0][4];
    expect(llm).toEqual({
      default: { provider: 'qwen-local', model: 'Qwen3-4B' },
      agents: {
        '7': { provider: 'ministral', model: 'Ministral-3B' },
        '11': { provider: 'qwen-local', model: 'Qwen3-4B' },
      },
      failure_policy: 'ordered_fallback',
      fallback_order: ['ministral'],
    });
  });

  it('omits the llm argument when no default provider is configured (legacy behavior)', async () => {
    useExperimentBuilder.setState({
      llmProviders: [],
      selectedProviderId: null,
      agentTypes: [],
      failurePolicy: 'pause_and_ask',
      fallbackProviderIds: [],
    });

    useSimulationStore.getState().runExperiment('2', 'Legacy experiment', [
      { name: 'A', ops: [] },
    ] as never);
    await new Promise((r) => setTimeout(r, 0));

    expect(experimentsMocks.createExperiment).toHaveBeenCalledTimes(1);
    expect(experimentsMocks.createExperiment.mock.calls[0][4]).toBeUndefined();
  });
});
