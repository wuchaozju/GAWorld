/**
 * Task 2913 — frontend duplicate-submit guard for Advance.
 *
 * Pins:
 * - a rapid double-click sends exactly ONE advance_chain request;
 * - an HTTP 409 ("node already advancing") is informational: no fatal
 *   error toast, no optimistic extra node, running state kept.
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

function baseState(overrides: Record<string, unknown> = {}) {
  return {
    currentSimulation: { id: 'sim-1', scene_type: 'policy_cascade_scene' },
    selectedNodeId: '0',
    nodes: [
      { id: '0', parentId: null, name: 'Node 0', depth: 0, isLeaf: false, status: 'completed' },
    ],
    agents: [],
    logs: [],
    rawEvents: [],
    isGenerating: false,
    isCompareMode: false,
    engineConfig: { endpoint: '/api', status: 'disconnected', token: undefined },
    addNotification: vi.fn(),
    ...overrides,
  } as never;
}

describe('advanceSimulation duplicate-submit guard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    treeMocks.getTreeGraph.mockResolvedValue({
      root: 0,
      frontier: [0],
      nodes: [{ id: 0, depth: 0 }],
      edges: [],
      running: [],
    });
    treeMocks.getSimEvents.mockResolvedValue([]);
    treeMocks.getSimState.mockResolvedValue({ turns: 1, agents: [], scene_config: {} });
    useSimulationStore.setState(baseState());
  });

  it('sends exactly ONE request on a rapid double-click', async () => {
    let release!: (value: { child: number }) => void;
    treeMocks.treeAdvanceChain.mockReturnValue(
      new Promise<{ child: number }>((resolve) => {
        release = resolve;
      }),
    );

    const first = useSimulationStore.getState().advanceSimulation();
    const second = useSimulationStore.getState().advanceSimulation();

    await vi.waitFor(() => expect(treeMocks.treeAdvanceChain).toHaveBeenCalledTimes(1));

    release({ child: 1 });
    await Promise.all([first, second]);
    expect(treeMocks.treeAdvanceChain).toHaveBeenCalledTimes(1);
    expect(useSimulationStore.getState().selectedNodeId).toBe('1');
  });

  it('treats a 409 as informational: no fatal error, no extra node', async () => {
    treeMocks.treeAdvanceChain.mockRejectedValue(new Error('409 Conflict'));

    await expect(useSimulationStore.getState().advanceSimulation()).resolves.toBeUndefined();

    expect(treeMocks.treeAdvanceChain).toHaveBeenCalledTimes(1);
    // No 504-style recovery polling for a new child — graph fetched once (before).
    expect(treeMocks.getTreeGraph).toHaveBeenCalledTimes(1);
    // Informational notification, not an error.
    const notify = useSimulationStore.getState().addNotification as ReturnType<typeof vi.fn>;
    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify.mock.calls[0][0]).toBe('info');
    expect(String(notify.mock.calls[0][1])).toMatch(/already/i);
    // No optimistic selection of an extra node.
    expect(useSimulationStore.getState().selectedNodeId).toBe('0');
    expect(useSimulationStore.getState().isGenerating).toBe(false);
  });

  it('is blocked while the store already reports an in-flight advance', async () => {
    useSimulationStore.setState(baseState({ isGenerating: true }));
    await useSimulationStore.getState().advanceSimulation();
    expect(treeMocks.treeAdvanceChain).not.toHaveBeenCalled();
    expect(treeMocks.getTreeGraph).not.toHaveBeenCalled();
  });
});
