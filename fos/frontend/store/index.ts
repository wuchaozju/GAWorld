// frontend/store/index.ts
//
// Main Zustand store composition.
//
// Responsibilities:
//   - Composes all slice functions into a single store
//   - Exports the combined AppState interface
//   - Maintains backward compatibility with existing imports
//
// Used by: All components that access the store

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { createSimulationSlice, SimulationSlice } from './simulation';
import { createAgentsSlice, AgentsSlice } from './agents';
import { createLogsSlice, LogsSlice } from './logs';
import { createUISlice, UISlice } from './ui';
import { createExperimentsSlice, ExperimentsSlice } from './experiments';
import { createEnvironmentSlice, EnvironmentSlice } from './environment';
import { createProvidersSlice, ProvidersSlice } from './providers';

// Combined AppState interface
export type AppState =
  SimulationSlice &
  AgentsSlice &
  LogsSlice &
  UISlice &
  ExperimentsSlice &
  EnvironmentSlice &
  ProvidersSlice;

// Create the composed store
export const useSimulationStore = create<AppState>()(
  devtools(
    (set, get, api) => {
      // Create each slice with full store access
      const simulationState = (createSimulationSlice as any)(set, get as any, api) as SimulationSlice;
      const agentsState = (createAgentsSlice as any)(set, get as any, api) as AgentsSlice;
      const logsState = (createLogsSlice as any)(set, get as any, api) as LogsSlice;
      const uiState = (createUISlice as any)(set, get as any, api) as UISlice;
      const experimentsState = (createExperimentsSlice as any)(set, get as any, api) as ExperimentsSlice;
      const environmentState = (createEnvironmentSlice as any)(set, get as any, api) as EnvironmentSlice;
      const providersState = (createProvidersSlice as any)(set, get as any, api) as ProvidersSlice;

      // Wire up cross-slice dependencies
      // Agents slice needs access to logs, notifications, selectedNodeId
      (agentsState as any).injectLog = logsState.injectLog;
      (agentsState as any).addNotification = uiState.addNotification;
      (agentsState as any).selectedNodeId = simulationState.selectedNodeId;
      (agentsState as any).logs = logsState.logs;

      // Environment slice needs access to various state
      (environmentState as any).logs = logsState.logs;
      (environmentState as any).agents = agentsState.agents;
      (environmentState as any).currentSimulation = simulationState.currentSimulation;
      (environmentState as any).addNotification = uiState.addNotification;
      (environmentState as any).selectedNodeId = simulationState.selectedNodeId;
      (environmentState as any).injectLog = logsState.injectLog;

      // Experiments slice needs access to various state
      (experimentsState as any).currentSimulation = simulationState.currentSimulation;
      (experimentsState as any).engineConfig = simulationState.engineConfig;
      (experimentsState as any).selectedNodeId = simulationState.selectedNodeId;
      (experimentsState as any).nodes = simulationState.nodes;
      (experimentsState as any).agents = agentsState.agents;
      (experimentsState as any).logs = logsState.logs;
      (experimentsState as any).rawEvents = logsState.rawEvents;
      (experimentsState as any).addNotification = uiState.addNotification;
      (experimentsState as any).isGenerating = uiState.isGenerating;
      (experimentsState as any).isGeneratingReport = uiState.isGeneratingReport;
      (experimentsState as any).timeConfig = simulationState.timeConfig;
      (experimentsState as any).currentProviderId = providersState.currentProviderId;
      (experimentsState as any).selectNode = simulationState.selectNode;

      // Logs slice needs access to selectedNodeId
      (logsState as any).selectedNodeId = simulationState.selectedNodeId;

      // Simulation slice needs access to agents, logs, notifications
      (simulationState as any).agents = agentsState.agents;
      (simulationState as any).logs = logsState.logs;
      (simulationState as any).rawEvents = logsState.rawEvents;
      (simulationState as any).addNotification = uiState.addNotification;

      // Return composed state
      return {
        ...simulationState,
        ...agentsState,
        ...logsState,
        ...uiState,
        ...experimentsState,
        ...environmentState,
        ...providersState
      };
    },
    { name: 'SimulationStore' }
  )
);

// Re-export helper functions for backward compatibility
export {
  generateAgentsWithAI,
  generateAgentsWithDemographics,
  mapBackendEventsToLogs,
  addTime,
  formatWorldTime,
  generateNodes,
  mapGraphToNodes,
  SYSTEM_TEMPLATES
} from './helpers';
