/**
 * Tests for reduction event mapping in helpers.ts.
 *
 * Tests for:
 * - mapBackendEventsToLogs handling reduction_action events
 * - Event display with reducer, target, amount, deduction
 * - i18n support for runtime language switching
 *
 * Updated to match backend terminology: reduction_action / reducer / deduction_*
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mapBackendEventsToLogs } from '../helpers';
import type { Agent } from '../../types';

describe('mapBackendEventsToLogs - reduction_action', () => {
  let mockAgents: Agent[];

  beforeEach(() => {
    vi.clearAllMocks();
    mockAgents = [
      { id: 'agent-1', name: 'Alice', role: '', avatarUrl: '', profile: '', llmConfig: { provider: 'mock', model: 'default' }, properties: {}, history: {}, memory: [], knowledgeBase: [] },
      { id: 'agent-2', name: 'Bob', role: '', avatarUrl: '', profile: '', llmConfig: { provider: 'mock', model: 'default' }, properties: {}, history: {}, memory: [], knowledgeBase: [] },
    ] as Agent[];
  });

  describe('Reduction Event Mapping', () => {
    it('should handle reduction_action event type', () => {
      const events = [
        {
          type: 'reduction_action',
          data: {
            reducer: 'Alice',
            target: 'Bob',
            amount: 3,
            deduction: 9,
            round: 1,
          },
        },
      ];

      const logs = mapBackendEventsToLogs(events, 'node-1', 1, mockAgents, true);

      expect(logs).toHaveLength(1);
      expect(logs[0].type).toBe('AGENT_ACTION');
      expect(logs[0].agentId).toBe('agent-1');
    });

    it('should display reducer name, target name, amount, and deduction', () => {
      const events = [
        {
          type: 'reduction_action',
          data: {
            reducer: 'Alice',
            target: 'Bob',
            amount: 3,
            deduction: 9,
            round: 1,
          },
        },
      ];

      const logs = mapBackendEventsToLogs(events, 'node-1', 1, mockAgents, true);

      expect(logs[0].content).toContain('Alice');
      expect(logs[0].content).toContain('Bob');
      expect(logs[0].content).toContain('3');
      expect(logs[0].content).toContain('9');
    });

    it('should use i18n for runtime language switching', () => {
      const events = [
        {
          type: 'reduction_action',
          data: {
            reducer: 'Alice',
            target: 'Bob',
            amount: 3,
            deduction: 9,
            round: 1,
          },
        },
      ];

      const logs = mapBackendEventsToLogs(events, 'node-1', 1, mockAgents, true);

      expect(logs[0].content).toBeDefined();
      expect(logs[0].content).toBeTruthy();
    });

    it('should use event round if provided, fallback to parameter round', () => {
      const events = [
        {
          type: 'reduction_action',
          data: {
            reducer: 'Alice',
            target: 'Bob',
            amount: 3,
            deduction: 9,
            round: 5,
          },
        },
      ];

      const logs = mapBackendEventsToLogs(events, 'node-1', 1, mockAgents, true);

      expect(logs[0].round).toBe(5);
    });

    it('should handle missing reducer gracefully', () => {
      const events = [
        {
          type: 'reduction_action',
          data: {
            target: 'Bob',
            amount: 3,
            deduction: 9,
            round: 1,
          },
        },
      ];

      const logs = mapBackendEventsToLogs(events, 'node-1', 1, mockAgents, true);

      expect(logs).toHaveLength(1);
      expect(logs[0].agentId).toBeUndefined();
    });
  });
});
