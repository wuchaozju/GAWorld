/*
This file turns log items into CSV text.
logsToCsv checks that it got a real non-empty list and then writes one CSV row for each log in a fixed column order.
*/

import Papa from 'papaparse';
import type { LogEntry } from '@/types';

export function logsToCsv(logs: LogEntry[]): string {
  if (!Array.isArray(logs) || logs.length === 0) {
    throw new Error('logsToCsv: logs must be a non-empty array');
  }

  const rows = logs.map((log) => ({
    round: log.round,
    agentId: log.agentId,
    type: log.type,
    content: log.content,
    timestamp: log.timestamp,
    nodeId: log.nodeId,
  }));

  return Papa.unparse(rows, { newline: '\n' });
}
