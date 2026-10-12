import { describe, it, expect } from 'vitest';
import { logsToCsv } from './logsToCsv';
import type { LogEntry } from '@/types';

const logs: LogEntry[] = [
  { id: 'l1', nodeId: 'n1', round: 1, type: 'AGENT_ACTION', agentId: 'a', content: 'chose allocate', timestamp: '2026-05-21T10:00:00.000Z' },
  { id: 'l2', nodeId: 'n1', round: 1, type: 'AGENT_SAY', agentId: 'b', content: 'I agree', timestamp: '2026-05-21T10:00:01.000Z' },
];

describe('logsToCsv', () => {
  it('produces a header row and one row per log in the fixed column order', () => {
    const csv = logsToCsv(logs);
    const lines = csv.split('\n');
    expect(lines[0]).toBe('round,agentId,type,content,timestamp,nodeId');
    expect(lines[1]).toBe('1,a,AGENT_ACTION,chose allocate,2026-05-21T10:00:00.000Z,n1');
    expect(lines[2]).toBe('1,b,AGENT_SAY,I agree,2026-05-21T10:00:01.000Z,n1');
    expect(lines).toHaveLength(3);
  });

  it('throws when given no logs', () => {
    expect(() => logsToCsv([])).toThrow();
  });
});
