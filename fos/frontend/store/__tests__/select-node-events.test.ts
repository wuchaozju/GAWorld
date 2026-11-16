/**
 * Tests that selectNode fetches events for the newly selected node.
 *
 * Bug: when clicking a different node in the simtree, logs/events for that
 * node were never loaded — only the initially selected node had data.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const treeMocks = vi.hoisted(() => ({
  getSimEvents: vi.fn(),
  getSimState: vi.fn(),
}));

vi.mock('../../services/simulationTree', () => ({
  getSimEvents: treeMocks.getSimEvents,
  getSimState: treeMocks.getSimState,
}));

import { useSimulationStore } from '../index';

describe('selectNode fetches events for the new node', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    treeMocks.getSimEvents.mockResolvedValue([]);
    treeMocks.getSimState.mockResolvedValue({
      turns: 2,
      agents: [],
      scene_config: {},
    });

    useSimulationStore.setState({
      currentSimulation: { id: 'sim-1' },
      selectedNodeId: '1',
      nodes: [
        { id: '1', parentId: null, name: 'Node 1', depth: 0, isLeaf: false },
        { id: '2', parentId: '1', name: 'Node 2', depth: 1, isLeaf: true },
        { id: '3', parentId: '1', name: 'Node 3', depth: 1, isLeaf: true },
      ],
      agents: [],
      logs: [
        {
          id: 'log-1',
          nodeId: '1',
          round: 1,
          type: 'SYSTEM',
          content: 'event on node 1',
          timestamp: new Date().toISOString(),
        },
      ],
      rawEvents: [{ type: 'system', data: { text: 'node 1 event' }, node: 1 }],
      engineConfig: {
        endpoint: '/api',
        status: 'connected',
        token: undefined,
      },
    } as never);
  });

  it('calls getSimEvents for the newly selected node', async () => {
    treeMocks.getSimEvents.mockResolvedValue([
      { type: 'system', data: { text: 'node 2 event' }, node: 2 },
    ]);

    await useSimulationStore.getState().selectNode('2');

    expect(treeMocks.getSimEvents).toHaveBeenCalledWith(
      '/api',
      'sim-1',
      2,
      undefined,
    );
  });

  it('replaces rawEvents with events for the selected node', async () => {
    const node2Events = [
      { type: 'system', data: { text: 'hello from node 2' }, node: 2 },
    ];
    treeMocks.getSimEvents.mockResolvedValue(node2Events);

    await useSimulationStore.getState().selectNode('2');

    const state = useSimulationStore.getState();
    expect(state.rawEvents).toEqual(node2Events);
  });

  it('replaces logs with logs for the selected node', async () => {
    treeMocks.getSimEvents.mockResolvedValue([
      { type: 'agent_action', data: { agent: 'Alice', content: 'speaking' }, node: 2 },
    ]);
    treeMocks.getSimState.mockResolvedValue({
      turns: 2,
      agents: [{ name: 'Alice', role: 'Mayor', properties: {} }],
      scene_config: {},
    });

    await useSimulationStore.getState().selectNode('2');

    const state = useSimulationStore.getState();
    const logsForNode2 = state.logs.filter((l: any) => l.nodeId === '2');
    expect(logsForNode2.length).toBeGreaterThan(0);
  });

  it('does not fetch events when selecting the same node', async () => {
    useSimulationStore.setState({ selectedNodeId: '1' } as never);

    await useSimulationStore.getState().selectNode('1');

    expect(treeMocks.getSimEvents).not.toHaveBeenCalled();
  });

  it('still updates selectedNodeId even if events fetch fails', async () => {
    treeMocks.getSimEvents.mockRejectedValue(new Error('network error'));

    await useSimulationStore.getState().selectNode('3');

    expect(useSimulationStore.getState().selectedNodeId).toBe('3');
  });

  it('updates agents when getSimState returns agent data', async () => {
    treeMocks.getSimState.mockResolvedValue({
      turns: 3,
      agents: [
        { name: 'Bob', role: 'Chef', properties: { skill: 'cooking' } },
      ],
      scene_config: {},
    });
    treeMocks.getSimEvents.mockResolvedValue([]);

    await useSimulationStore.getState().selectNode('3');

    const state = useSimulationStore.getState();
    expect(state.agents.length).toBeGreaterThan(0);
    expect(state.agents[0].name).toBe('Bob');
  });
});
