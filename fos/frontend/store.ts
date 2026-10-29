// frontend/store.ts
//
// Re-exports from the refactored slice-based store.
//
// The store has been split into focused slice files in the store/ directory:
//   - store/index.ts       - Main store composition
//   - store/simulation.ts  - Simulation CRUD, nodes, templates
//   - store/agents.ts      - Agent management
//   - store/logs.ts        - Log mapping, events
//   - store/ui.ts          - UI state, modals, notifications
//   - store/experiments.ts - Experiments, comparison, reports
//   - store/environment.ts - Environment suggestions
//   - store/providers.ts   - LLM provider management
//   - store/helpers.ts     - Pure helper functions
//
// This file maintains backward compatibility with existing imports.

// Main store and types
export { useSimulationStore, type AppState } from './store/index';

// Helper functions for backward compatibility
export {
  generateAgentsWithAI,
  generateAgentsWithDemographics,
  mapBackendEventsToLogs,
  addTime,
  formatWorldTime,
  generateNodes,
  mapGraphToNodes,
  SYSTEM_TEMPLATES,
  fetchEnvironmentSuggestions
} from './store/helpers';
