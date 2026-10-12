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

import { useSimulationStore } from '../index';

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
