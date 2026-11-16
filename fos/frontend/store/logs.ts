// frontend/store/logs.ts
//
// Logs and events management slice.
//
// Responsibilities:
//   - Manages log entries and raw events
//   - Provides injectLog for host interventions
//   - Imports helper functions for event-to-log mapping
//
// Used by: LogViewer, SimulationPage, any component displaying logs

import { StateCreator } from 'zustand';
import type { LogEntry } from '../types';

export interface LogsSlice {
  // State
  logs: LogEntry[];
  rawEvents: any[];

  // Actions
  injectLog: (type: LogEntry['type'], content: string, imageUrl?: string, audioUrl?: string, videoUrl?: string) => void;
  setLogs: (logs: LogEntry[]) => void;
  setRawEvents: (events: any[]) => void;
}

export const createLogsSlice: StateCreator<
  LogsSlice,
  [],
  [],
  LogsSlice
> = (set, get) => ({
  // Initial state
  logs: [],
  rawEvents: [],

  // Actions
  injectLog: (type, content, imageUrl, audioUrl, videoUrl) => {
    const selectedNodeId = (get() as any).selectedNodeId;
    if (!selectedNodeId) return;

    const log: LogEntry = {
      id: `host-${Date.now()}`,
      nodeId: selectedNodeId,
      round: 0,
      type: type === 'SYSTEM' || type === 'ENVIRONMENT' ? type : 'HOST_INTERVENTION',
      content: content,
      imageUrl,
      audioUrl,
      videoUrl,
      timestamp: new Date().toISOString()
    };

    set({ logs: [...get().logs, log] });
  },

  setLogs: (logs) => set({ logs }),
  setRawEvents: (events) => set({ rawEvents: events })
});
