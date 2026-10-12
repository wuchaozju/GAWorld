/**
 * This file checks that the analysis tab shows simulation results.
 *
 * agent makes a small test agent with history values.
 * simNode makes a small branch in the simulation tree.
 * renderWithUser shows a screen and gives tests a person-like click helper.
 * The tests make sure the results view shows charts and lets people choose a branch.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useSimulationStore, type AppState } from '@/store';
import type { SimNode } from '@/types';
import { AnalyseTab } from '../AnalyseTab';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

const agent = (id: string, name: string, history: Record<string, number[]>) => ({
  id, name, role: '', avatarUrl: '', profile: '',
  llmConfig: { provider: 'mock', model: 'default' },
  properties: {}, history, memory: [], knowledgeBase: [],
});

const simNode = (
  id: string,
  displayId: string,
  name: string,
  parentId: string | null,
  depth: number,
): SimNode => ({
  id,
  display_id: displayId,
  name,
  parentId,
  depth,
  isLeaf: true,
  status: 'completed',
  timestamp: '2026-05-21T10:00:00.000Z',
  worldTime: '2026-01-01T00:00:00.000Z',
});

function renderWithUser(ui: React.ReactElement) {
  const result = render(ui);
  return { ...result, user: userEvent.setup() };
}

beforeEach(() => {
  useSimulationStore.setState({
    currentSimulation: {
      id: 's1',
      name: 'Test sim',
      templateId: 't',
      status: 'active',
      createdAt: '',
      timeConfig: { baseTime: '2026-01-01T00:00:00.000Z', unit: 'day', step: 1 },
      socialNetwork: {},
    },
    agents: [agent('a', 'Alice', { score: [10, 12, 15] })],
    logs: [{ id: 'l1', nodeId: 'n1', round: 1, type: 'AGENT_ACTION', agentId: 'a', content: 'x', timestamp: '2026-05-21T10:00:00.000Z' }],
    resultsSummary: null,
    isGeneratingResultsSummary: false,
    resultsSummaryError: null,
    toggleAnalytics: vi.fn(),
    toggleReportModal: vi.fn(),
    nodes: [
      simNode('root', '0', 'Root', null, 0),
      simNode('n1', '0.1', 'Branch A', 'root', 1),
      simNode('n2', '0.2', 'Branch B', 'root', 1),
    ],
    selectedNodeId: 'root',
    selectNode: vi.fn(async () => undefined),
  } satisfies Partial<AppState>);
});

describe('AnalyseTab - results sub-view', () => {
  it('defaults to the results sub-view and renders the real generate button and a chart polyline', () => {
    const { container } = render(<AnalyseTab />);
    expect(screen.getByRole('button', { name: 'results.generate' })).toBeTruthy();
    expect(container.querySelectorAll('polyline').length).toBeGreaterThan(0);
    expect(screen.getByText('Alice')).toBeTruthy();
  });

  it('renders a branch selector dropdown with all nodes', () => {
    render(<AnalyseTab />);
    const select = screen.getByLabelText('results.branch');
    expect(select).toBeTruthy();
    const options = select.querySelectorAll('option');
    expect(options.length).toBe(3);
    expect(options[0].textContent).toContain('0');
    expect(options[0].textContent).toContain('Root');
    expect(options[1].textContent).toContain('0.1');
    expect(options[1].textContent).toContain('Branch A');
    expect(options[2].textContent).toContain('0.2');
    expect(options[2].textContent).toContain('Branch B');
  });

  it('calls selectNode when the user picks a different branch', async () => {
    const { user } = renderWithUser(<AnalyseTab />);
    const select = screen.getByLabelText('results.branch');
    await user.selectOptions(select, 'n2');
    const state = useSimulationStore.getState();
    expect(state.selectNode).toHaveBeenCalledWith('n2');
  });
});
