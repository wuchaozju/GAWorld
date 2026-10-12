import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import SimulationPage from '../../pages/SimulationPage';
import { useSimulationStore } from '../../store';
import { useAuthStore } from '../../store/auth';

const translations: Record<string, string> = {
  'simPage.enterSteps': 'Enter number of steps (1–100)',
  'simPage.advanceControls': 'Advance controls',
  'simPage.autoAdvance': 'Auto advance',
  'simPage.stop': 'Stop',
  'simPage.advance': 'Advance node',
  'simPage.advancing': 'Advancing…',
  'simPage.branch': 'Create branch',
  'sim.running': 'Running',
  'sim.agents': 'agents',
  'simPage.advancingProgress': 'Step {{current}}/{{total}}',
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, any>) => {
      const base = translations[key] ?? key;
      if (params) {
        return base.replace(/{{(\w+)}}/g, (_, p) => params[p]?.toString() || '');
      }
      return base;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: vi.fn() },
}));

vi.mock('../../components/SimTree', () => ({
  SimTree: () => <div>Sim Tree Panel</div>,
}));

vi.mock('../../components/LogViewer', () => {
  const React = require('react');
  const { useState } = React;

  return {
    LogViewer: () => {
      const [steps, setSteps] = (useState as any)(1);
      return (
        <div>
          <div>Log Viewer Panel</div>
          <div role="group" aria-label="Advance controls">
            <input
              type="number"
              title="Enter number of steps (1–100)"
              value={steps}
              onChange={(e: any) => setSteps(Number(e.target.value))}
            />
            <button>Advance node</button>
          </div>
        </div>
      );
    },
  };
});

vi.mock('../../components/WorkspaceRunControls', () => ({
  WorkspaceRunControls: () => null,
}));

vi.mock('../../components/ComparisonView', () => ({
  ComparisonView: () => <div>Comparison Panel</div>,
}));

vi.mock('../../components/PeekOverlay', () => ({
  PeekOverlay: () => null,
}));

const renderPage = () => render(
  <MemoryRouter>
    <SimulationPage />
  </MemoryRouter>
);

describe('Auto-advance — full integration flow', () => {
  beforeEach(() => {
    const mockAdvance = vi.fn().mockResolvedValue(undefined);
    const mockNotify = vi.fn();

    useAuthStore.setState({
      isAuthenticated: false,
      hasRestored: true,
    });

    useSimulationStore.setState({
      currentSimulation: { id: 'sim-1', name: 'Test Sim' },
      selectedNodeId: '1',
      nodes: [{ id: '1', parentId: null, name: 'Root', depth: 0, isLeaf: true }],
      activeTab: 'workspace',
      isAutoAdvancing: false,
      isGenerating: false,
      isCompareMode: false,
      autoAdvanceTotal: 0,
      autoAdvanceCurrent: 0,
      highlightedNodeId: null,
      advanceSimulation: mockAdvance,
      addNotification: mockNotify,
      engineConfig: { endpoint: '' },
    } as any);
  });

  it('should complete a full auto-advance run of 3 steps', async () => {
    renderPage();

    const input = screen.getByTitle(/enter number of steps/i);
    fireEvent.change(input, { target: { value: '3' } });

    await act(async () => {
      useSimulationStore.getState().startAutoAdvance(3);
    });

    await waitFor(() => {
      const state = useSimulationStore.getState() as any;
      expect(state.isAutoAdvancing).toBe(false);
    }, { timeout: 5000 });

    const state = useSimulationStore.getState() as any;
    expect(state.advanceSimulation).toHaveBeenCalledTimes(3);
    expect(state.addNotification).toHaveBeenCalledWith(
      'success',
      expect.any(String)
    );
  });

  it('should stop mid-run when stop is clicked', async () => {
    const slowAdvance = vi.fn().mockImplementation(
      () => new Promise((r) => setTimeout(r, 200))
    );
    useSimulationStore.setState({
      advanceSimulation: slowAdvance,
    } as any);

    renderPage();

    await act(async () => {
      useSimulationStore.getState().startAutoAdvance(20);
    });

    await waitFor(() => {
      expect(useSimulationStore.getState().isAutoAdvancing).toBe(true);
    });

    await act(async () => {
      useSimulationStore.getState().stopAutoAdvance();
    });

    await waitFor(() => {
      expect(useSimulationStore.getState().isAutoAdvancing).toBe(false);
    });
    expect(slowAdvance.mock.calls.length).toBeLessThan(20);
  });
});
