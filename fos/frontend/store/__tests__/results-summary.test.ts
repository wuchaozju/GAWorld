/**
 * These tests check how the store builds an AI analysis summary.
 *
 * They verify metric extraction, empty data handling, branch filtering, and the
 * request sent to the summary service.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/services/client', () => ({ apiClient: { post: vi.fn() } }));

import { apiClient } from '@/services/client';
import { useSimulationStore } from '@/store';
import type { Agent, LogEntry } from '@/types';

const post = vi.mocked(apiClient.post);

const agent = (id: string, name: string, history: Record<string, number[]>): Agent => ({
  id, name, role: '', avatarUrl: '', profile: '',
  llmConfig: { provider: 'mock', model: 'default' },
  properties: {}, history, memory: [], knowledgeBase: [],
});

const logWithOutcome = (agentId: string, round: number, outcome: Record<string, number>): LogEntry => ({
  id: `lo-${round}-${agentId}`,
  nodeId: 'n1',
  round,
  type: 'AGENT_ACTION',
  agentId,
  content: 'x',
  timestamp: '2026-05-21T10:00:00.000Z',
  outcome,
});

beforeEach(() => {
  post.mockReset();
  useSimulationStore.setState({
    agents: [agent('a', 'Alice', { score: [10, 12, 15] })],
    currentProviderId: 7,
    resultsSummary: null,
    isGeneratingResultsSummary: false,
    resultsSummaryError: null,
  } as any);
});

describe('generateResultsSummary', () => {
  it('sends the computed metrics to the LLM and stores the returned prose', async () => {
    post.mockResolvedValue({ data: { text: 'The agents cooperated.' } } as any);

    await (useSimulationStore.getState() as any).generateResultsSummary('Public goods game', 'en');

    expect(post).toHaveBeenCalledTimes(1);
    const [endpoint, body] = post.mock.calls[0] as any;
    expect(endpoint).toBe('llm/refine_report');
    expect(body.provider_id).toBe(7);
    expect(body.prompt).toContain('- Alice: 10, 12, 15 (final: 15)');

    const s = useSimulationStore.getState() as any;
    expect(s.resultsSummary).toBe('The agents cooperated.');
    expect(s.isGeneratingResultsSummary).toBe(false);
    expect(s.resultsSummaryError).toBeNull();
  });

  it('records the error and rethrows when the LLM call fails, storing no fake summary', async () => {
    post.mockRejectedValue(new Error('network down'));

    await expect(
      (useSimulationStore.getState() as any).generateResultsSummary('X', 'en'),
    ).rejects.toThrow('network down');

    const s = useSimulationStore.getState() as any;
    expect(s.resultsSummary).toBeNull();
    expect(s.isGeneratingResultsSummary).toBe(false);
    expect(s.resultsSummaryError).toBe('network down');
  });

  it('surfaces the backend error detail when refine_report fails', async () => {
    post.mockRejectedValue(
      Object.assign(new Error('Request failed with status code 500'), {
        response: { data: { error: 'DeepSeek API: 401 Unauthorized' } },
      }),
    );
    useSimulationStore.setState({
      agents: [
        agent('a', 'Alice', {}),
        agent('b', 'Bob', {}),
      ],
      logs: [
        logWithOutcome('a', 1, { payoff: 10 }),
        logWithOutcome('b', 1, { payoff: 8 }),
      ],
      currentProviderId: 7,
    } as any);

    try {
      await expect(
        (useSimulationStore.getState() as any).generateResultsSummary('Test', 'en'),
      ).rejects.toThrow('Request failed with status code 500');

      expect((useSimulationStore.getState() as any).resultsSummaryError).toBe(
        'DeepSeek API: 401 Unauthorized',
      );
    } finally {
      useSimulationStore.setState({ logs: [] } as any);
    }
  });

  it('throws when no LLM provider is selected, without calling the LLM', async () => {
    useSimulationStore.setState({ currentProviderId: null } as any);
    await expect(
      (useSimulationStore.getState() as any).generateResultsSummary('X', 'en'),
    ).rejects.toThrow();
    expect(post).not.toHaveBeenCalled();
    expect((useSimulationStore.getState() as any).resultsSummary).toBeNull();
  });

  it('throws when there are no scored metrics, without calling the LLM', async () => {
    useSimulationStore.setState({ agents: [agent('a', 'Alice', {})] } as any);
    await expect(
      (useSimulationStore.getState() as any).generateResultsSummary('X', 'en'),
    ).rejects.toThrow();
    expect(post).not.toHaveBeenCalled();
  });

  it('generates a summary by hydrating history from log outcomes when agent.history is empty', async () => {
    post.mockResolvedValue({ data: { text: 'The agents cooperated.' } } as any);
    useSimulationStore.setState({
      agents: [
        agent('a', 'Alice', {}),
        agent('b', 'Bob', {}),
      ],
      logs: [
        logWithOutcome('a', 1, { payoff: 10 }),
        logWithOutcome('b', 1, { payoff: 8 }),
        logWithOutcome('a', 2, { payoff: 12 }),
        logWithOutcome('b', 2, { payoff: 9 }),
      ],
      currentProviderId: 7,
    } as any);

    await (useSimulationStore.getState() as any).generateResultsSummary('Test', 'en');

    const s = useSimulationStore.getState() as any;
    expect(s.resultsSummary).toBe('The agents cooperated.');
    expect(s.resultsSummaryError).toBeNull();
  });

  it('builds the summary from the selected branch path only', async () => {
    post.mockResolvedValue({ data: { text: 'Branch A only.' } } as any);
    useSimulationStore.setState({
      selectedNodeId: '4',
      nodes: [
        { id: '0', parentId: null, name: 'Root', depth: 0, isLeaf: false },
        { id: '1', parentId: '0', name: 'Branch A', depth: 1, isLeaf: false },
        { id: '2', parentId: '0', name: 'Branch B', depth: 1, isLeaf: false },
        { id: '4', parentId: '1', name: 'Leaf A', depth: 2, isLeaf: true },
        { id: '5', parentId: '2', name: 'Leaf B', depth: 2, isLeaf: true },
      ],
      agents: [agent('a', 'Alice', {})],
      logs: [
        { ...logWithOutcome('a', 1, { amount: 5 }), id: 'branch-a', nodeId: '4' },
        { ...logWithOutcome('a', 1, { amount: 10 }), id: 'branch-b', nodeId: '5' },
      ],
      currentProviderId: 7,
    } as any);

    await (useSimulationStore.getState() as any).generateResultsSummary('Test', 'en');

    const [, body] = post.mock.calls[0] as any;
    expect(body.prompt).toContain('- Alice: 5 (final: 5)');
    expect(body.prompt).not.toContain('- Alice: 10 (final: 10)');
  });
});
