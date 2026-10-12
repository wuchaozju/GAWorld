// Test setup file
import { expect, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import * as matchers from '@testing-library/jest-dom/matchers';

// Extend Vitest's expect with jest-dom matchers
expect.extend(matchers);

// Cleanup after each test
afterEach(() => {
  cleanup();
});

// Minimal WebGL mocks for sigma.js (used by SimTree component)
(globalThis as any).WebGLRenderingContext = class WebGLRenderingContext {};
(globalThis as any).WebGL2RenderingContext = class WebGL2RenderingContext {};

// Make i18n available globally for stores BEFORE importing modules
(globalThis as any).i18n = {
  t: (key: string, params?: Record<string, any>) => {
    if (params) {
      return key.replace(/{{(\w+)}}/g, (_, p) => params[p]?.toString() || '');
    }
    return key;
  },
  language: 'en'
};

// Mock i18n module
vi.mock('../i18n', () => ({
  default: {
    t: (key: string, params?: Record<string, any>) => (globalThis as any).i18n.t(key, params),
    language: 'en',
    init: vi.fn(() => Promise.resolve())
  },
  setLanguage: vi.fn(() => Promise.resolve()),
}));

// Mock API client
vi.mock('../services/client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  }
}));

// Mock all API imports
vi.mock('../services/simulations', () => ({
  createSimulation: vi.fn(() => Promise.resolve({ id: 'sim-123', name: 'Test Sim' })),
  getSimulation: vi.fn(() => Promise.resolve({ id: 'sim-123', name: 'Test Sim' })),
  updateSimulation: vi.fn(() => Promise.resolve()),
  resetSimulation: vi.fn(() => Promise.resolve()),
  deleteSimulation: vi.fn(() => Promise.resolve()),
  getSimulations: vi.fn(() => Promise.resolve([])),
  startSimulation: vi.fn(() => Promise.resolve())
}));

vi.mock('../services/simulationTree', () => ({
  getTreeGraph: vi.fn(() => Promise.resolve({
    root: 0,
    nodes: [{ id: 0, depth: 0, status: 'completed' }],
    edges: [],
    running: []
  })),
  treeAdvanceChain: vi.fn(() => Promise.resolve({ child: 1 })),
  treeBranch: vi.fn(() => Promise.resolve({ child: 2 })),
  treeBranchPublic: vi.fn(() => Promise.resolve({ child: 2 })),
  getSimEvents: vi.fn(() => Promise.resolve([])),
  treeDeleteSubtree: vi.fn(() => Promise.resolve())
}));

vi.mock('../services/experiments', () => ({
  submitExperiment: vi.fn(() => Promise.resolve({ run_id: 'run-123' })),
  getExperimentRun: vi.fn(() => Promise.resolve({ status: 'completed' }))
}));

vi.mock('../services/environmentSuggestions', () => ({
  getSuggestionStatus: vi.fn(() => Promise.resolve({ available: false })),
  generateSuggestions: vi.fn(() => Promise.resolve([])),
  applyEnvironmentEvent: vi.fn(() => Promise.resolve()),
  dismissSuggestions: vi.fn(() => Promise.resolve())
}));
