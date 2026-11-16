import { describe, it, expect } from 'vitest';
import { mapBackendEventsToLogs } from '../helpers';
import type { Agent } from '@/types';

const agent = (id: string, name: string): Agent => ({
  id, name, role: '', avatarUrl: '', profile: '',
  llmConfig: { provider: 'mock', model: 'default' },
  properties: {}, history: {}, memory: [], knowledgeBase: [],
});
const agents = [agent('a', 'Agent 1')];

describe('mapBackendEventsToLogs â€” experiment_action outcome field', () => {
  it('populates outcome with payoff and numeric parameters', () => {
    const events = [{
      type: 'experiment_action',
      data: {
        agent: 'Agent 1', action: 'allocate',
        parameters: { amount: 10 },
        summary: 'Agent 1 chose allocate (amount=10)',
        payoff: 11.7, round: 1, success: true, skipped: false,
      },
    }];
    const logs = mapBackendEventsToLogs(events, 'n1', 1, agents);
    expect(logs[0].outcome).toEqual({ payoff: 11.7, amount: 10 });
  });

  it('populates outcome in the no-summary path', () => {
    const events = [{
      type: 'experiment_action',
      data: {
        agent: 'Agent 1', action: 'allocate',
        parameters: { amount: 7 },
        payoff: 10.5, round: 2, success: true, skipped: false,
      },
    }];
    const logs = mapBackendEventsToLogs(events, 'n1', 2, agents);
    expect(logs[0].outcome).toEqual({ payoff: 10.5, amount: 7 });
  });

  it('sets outcome to payoff-only when parameters have no numeric values', () => {
    const events = [{
      type: 'experiment_action',
      data: {
        agent: 'Agent 1', action: 'cooperate',
        parameters: {},
        payoff: 3.5, round: 1, success: true, skipped: false,
      },
    }];
    const logs = mapBackendEventsToLogs(events, 'n1', 1, agents);
    expect(logs[0].outcome).toEqual({ payoff: 3.5 });
  });

  it('leaves outcome undefined when there is no payoff and no numeric parameters', () => {
    const events = [{
      type: 'experiment_action',
      data: {
        agent: 'Agent 1', action: 'speak',
        parameters: { message: 'hello' },
        payoff: null, round: 1, success: true, skipped: false,
      },
    }];
    const logs = mapBackendEventsToLogs(events, 'n1', 1, agents);
    expect(logs[0].outcome).toBeUndefined();
  });
});
