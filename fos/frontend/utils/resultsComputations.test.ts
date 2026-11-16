import { describe, it, expect } from 'vitest';
import type { Agent, LogEntry } from '@/types';
import {
  listMetrics,
  computeMetricTrajectories,
  computeMetricAggregate,
  computeEventCountByAgent,
  computeEventCountByRound,
  hydrateAgentHistoryFromLogs,
} from './resultsComputations';

const agent = (id: string, name: string, history: Record<string, number[]>): Agent => ({
  id, name, role: '', avatarUrl: '', profile: '',
  llmConfig: { provider: 'mock', model: 'default' },
  properties: {}, history, memory: [], knowledgeBase: [],
});

const log = (id: string, round: number, type: LogEntry['type'], agentId?: string): LogEntry => ({
  id, nodeId: 'n1', round, type, content: 'x', timestamp: '2026-05-21T10:00:00.000Z',
  ...(agentId !== undefined ? { agentId } : {}),
});

const logWithOutcome = (agentId: string, round: number, outcome: Record<string, number>): LogEntry => ({
  id: `lo-${round}-${agentId}`, nodeId: 'n1', round, type: 'AGENT_ACTION',
  agentId, content: 'x', timestamp: '2026-05-21T10:00:00.000Z', outcome,
});

const alice = agent('a', 'Alice', { score: [10, 12, 15], cooperation: [1, 1, 0] });
const bob = agent('b', 'Bob', { score: [8, 9, 9] });
const charlie = agent('c', 'Charlie', {});

describe('listMetrics', () => {
  it('returns the sorted union of history keys across all agents', () => {
    expect(listMetrics([alice, bob, charlie])).toEqual(['cooperation', 'score']);
  });
  it('returns an empty array when no agent has any history', () => {
    expect(listMetrics([charlie])).toEqual([]);
    expect(listMetrics([])).toEqual([]);
  });
  it('throws when agents is not an array', () => {
    // @ts-expect-error testing runtime guard
    expect(() => listMetrics('nope')).toThrow();
  });
});

describe('computeMetricTrajectories', () => {
  it('returns one series per agent that recorded the metric, sorted by name', () => {
    expect(computeMetricTrajectories([bob, alice, charlie], 'score')).toEqual([
      { agentId: 'a', agentName: 'Alice', values: [10, 12, 15] },
      { agentId: 'b', agentName: 'Bob', values: [8, 9, 9] },
    ]);
  });
  it('omits agents that did not record the metric', () => {
    expect(computeMetricTrajectories([alice, bob, charlie], 'cooperation')).toEqual([
      { agentId: 'a', agentName: 'Alice', values: [1, 1, 0] },
    ]);
  });
  it('throws when no agent recorded the metric', () => {
    expect(() => computeMetricTrajectories([alice, bob], 'nonexistent')).toThrow();
  });
  it('throws when metric is empty', () => {
    expect(() => computeMetricTrajectories([alice], '')).toThrow();
  });
});

describe('computeMetricAggregate', () => {
  it('computes per-round mean, min, and max across agents', () => {
    const series = [
      { agentId: 'a', agentName: 'A', values: [10, 20] },
      { agentId: 'b', agentName: 'B', values: [20, 40] },
    ];
    expect(computeMetricAggregate(series)).toEqual([
      { round: 1, mean: 15, min: 10, max: 20 },
      { round: 2, mean: 30, min: 20, max: 40 },
    ]);
  });

  it('aggregates only the values present in each round for ragged series', () => {
    const series = [
      { agentId: 'a', agentName: 'A', values: [10, 20, 30] },
      { agentId: 'b', agentName: 'B', values: [20] },
    ];
    expect(computeMetricAggregate(series)).toEqual([
      { round: 1, mean: 15, min: 10, max: 20 },
      { round: 2, mean: 20, min: 20, max: 20 },
      { round: 3, mean: 30, min: 30, max: 30 },
    ]);
  });

  it('throws on an empty series array', () => {
    expect(() => computeMetricAggregate([])).toThrow();
  });
});

describe('computeEventCountByAgent', () => {
  const logs = [
    log('l1', 1, 'AGENT_ACTION', 'a'),
    log('l2', 1, 'AGENT_SAY', 'b'),
    log('l3', 1, 'SYSTEM'),
    log('l4', 2, 'AGENT_ACTION', 'a'),
    log('l5', 2, 'AGENT_ACTION', 'a'),
    log('l6', 2, 'ENVIRONMENT'),
  ];

  it('counts agent-attributed events per agent, sorted by count desc', () => {
    expect(computeEventCountByAgent(logs)).toEqual([
      { agentId: 'a', count: 3 },
      { agentId: 'b', count: 1 },
    ]);
  });

  it('ignores entries with no agentId', () => {
    expect(computeEventCountByAgent([log('s', 1, 'SYSTEM')])).toEqual([]);
  });

  it('returns an empty array for no logs', () => {
    expect(computeEventCountByAgent([])).toEqual([]);
  });

  it('throws when logs is not an array', () => {
    // @ts-expect-error testing runtime guard
    expect(() => computeEventCountByAgent('nope')).toThrow();
  });
});

describe('computeEventCountByRound', () => {
  const logs = [
    log('l1', 1, 'AGENT_ACTION', 'a'),
    log('l2', 1, 'AGENT_SAY', 'b'),
    log('l3', 1, 'SYSTEM'),
    log('l4', 2, 'AGENT_ACTION', 'a'),
    log('l5', 2, 'AGENT_ACTION', 'a'),
    log('l6', 2, 'ENVIRONMENT'),
  ];

  it('counts all events per round, sorted by round ascending', () => {
    expect(computeEventCountByRound(logs)).toEqual([
      { round: 1, count: 3 },
      { round: 2, count: 3 },
    ]);
  });

  it('returns an empty array for no logs', () => {
    expect(computeEventCountByRound([])).toEqual([]);
  });

  it('throws when logs is not an array', () => {
    // @ts-expect-error testing runtime guard
    expect(() => computeEventCountByRound('nope')).toThrow();
  });
});

describe('hydrateAgentHistoryFromLogs', () => {
  it('builds history arrays from log outcome data, grouped by agent and round', () => {
    const logs = [
      logWithOutcome('a', 1, { payoff: 10, amount: 5 }),
      logWithOutcome('b', 1, { payoff: 8, amount: 10 }),
      logWithOutcome('a', 2, { payoff: 12, amount: 7 }),
      logWithOutcome('b', 2, { payoff: 9, amount: 8 }),
    ];
    const result = hydrateAgentHistoryFromLogs(logs, [alice, bob]);
    const a = result.find((r) => r.id === 'a');
    const b = result.find((r) => r.id === 'b');
    expect(a?.history['payoff']).toEqual([10, 12]);
    expect(a?.history['amount']).toEqual([5, 7]);
    expect(b?.history['payoff']).toEqual([8, 9]);
    expect(b?.history['amount']).toEqual([10, 8]);
  });

  it('fills missing rounds with 0 to keep arrays dense', () => {
    const logs = [
      logWithOutcome('a', 1, { payoff: 10 }),
      logWithOutcome('a', 3, { payoff: 15 }),
    ];
    const result = hydrateAgentHistoryFromLogs(logs, [alice]);
    expect(result[0].history['payoff']).toEqual([10, 0, 15]);
  });

  it('does not overwrite an agent history key that already has values', () => {
    const existing = agent('a', 'Alice', { payoff: [99, 98] });
    const logs = [
      logWithOutcome('a', 1, { payoff: 10 }),
      logWithOutcome('a', 2, { payoff: 12 }),
    ];
    const result = hydrateAgentHistoryFromLogs(logs, [existing]);
    expect(result[0].history['payoff']).toEqual([99, 98]);
  });

  it('adds new metrics from logs even when other history keys already exist', () => {
    const existing = agent('a', 'Alice', { payoff: [99, 98] });
    const logs = [
      logWithOutcome('a', 1, { payoff: 10, amount: 5 }),
      logWithOutcome('a', 2, { payoff: 12, amount: 7 }),
    ];
    const result = hydrateAgentHistoryFromLogs(logs, [existing]);
    expect(result[0].history['payoff']).toEqual([99, 98]);
    expect(result[0].history['amount']).toEqual([5, 7]);
  });

  it('returns agents unchanged when no logs have outcome data', () => {
    const logs = [log('s', 1, 'SYSTEM')];
    const emptyAlice = agent('a', 'Alice', {});
    const emptyBob = agent('b', 'Bob', {});
    const result = hydrateAgentHistoryFromLogs(logs, [emptyAlice, emptyBob]);
    expect(result[0].history).toEqual({});
    expect(result[1].history).toEqual({});
  });

  it('throws when logs is not an array', () => {
    // @ts-expect-error testing runtime guard
    expect(() => hydrateAgentHistoryFromLogs('nope', [alice])).toThrow();
  });

  it('throws when agents is not an array', () => {
    // @ts-expect-error testing runtime guard
    expect(() => hydrateAgentHistoryFromLogs([], 'nope')).toThrow();
  });
});
