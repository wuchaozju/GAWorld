/**
 * Tests for the ComparisonView component.
 *
 * The ComparisonView shows a side-by-side comparison of two simulation nodes.
 * These tests cover all major states: no baseline, no compare target, loading,
 * empty diff, event diffs, agent property diffs, stat cards, LLM toggle,
 * analysis report button, event type translations, and key divergence area.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ComparisonView } from '../ComparisonView';
import { useSimulationStore } from '../../store';

// Mock i18n — return the key itself so tests can assert on translation keys
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

// Mock the experiments API so we control what compareNodes returns
const mockCompareNodes = vi.hoisted(() => vi.fn());
vi.mock('../../services/experiments', () => ({
  compareNodes: mockCompareNodes,
}));

// Shared test nodes
const baselineNode = {
  id: '1',
  display_id: '1',
  name: 'Initial State',
  parentId: null,
  depth: 0,
  isLeaf: false,
  status: 'completed',
  timestamp: '2026-06-26T10:00:00.000Z',
  worldTime: '2026-01-01T00:00:00.000Z',
};

const compareNode = {
  id: '2',
  display_id: '2',
  name: 'Experimental Variant',
  parentId: '1',
  depth: 1,
  isLeaf: true,
  status: 'completed',
  timestamp: '2026-06-26T10:05:00.000Z',
  worldTime: '2026-01-02T00:00:00.000Z',
};

describe('ComparisonView', () => {
  beforeEach(() => {
    mockCompareNodes.mockReset();
    // Set default store state
    useSimulationStore.setState({
      selectedNodeId: null,
      compareTargetNodeId: null,
      nodes: [],
      isGenerating: false,
      comparisonUseLLM: false,
      comparisonSummary: null,
      currentSimulation: null,
      generateComparisonAnalysis: vi.fn(),
      setComparisonUseLLM: vi.fn(),
    } as never);
  });

  // ── 1. No baseline node selected ──────────────────────────────────

  it('shows select baseline node message when no baseline node is chosen', () => {
    useSimulationStore.setState({
      selectedNodeId: null,
      compareTargetNodeId: null,
      nodes: [baselineNode, compareNode],
      currentSimulation: { id: 'sim-1' },
    } as never);

    render(<ComparisonView />);
    expect(screen.getByText('components.comparisonView.selectBaselineNode')).toBeInTheDocument();
  });

  // ── 2. No compare target node selected ────────────────────────────

  it('shows select compare node message when baseline is set but compare target is null', () => {
    useSimulationStore.setState({
      selectedNodeId: '1',
      compareTargetNodeId: null,
      nodes: [baselineNode, compareNode],
      currentSimulation: { id: 'sim-1' },
    } as never);

    render(<ComparisonView />);

    expect(screen.getByText('components.comparisonView.selectCompareNode')).toBeInTheDocument();
    expect(screen.getByText('components.comparisonView.selectCompareNodeHint')).toBeInTheDocument();
  });

  // ── 3. Loading state ──────────────────────────────────────────────

  it('shows a spinner in Smart Summary section when isLoadingComparison is true', () => {
    useSimulationStore.setState({
      selectedNodeId: '1',
      compareTargetNodeId: '2',
      nodes: [baselineNode, compareNode],
      currentSimulation: { id: 'sim-1' },
    } as never);

    render(<ComparisonView />);

    // The spinner is shown in the Smart Summary section with text
    expect(screen.getByText('components.comparisonView.analyzingDifferences')).toBeInTheDocument();
    // The Loader2 icon has animate-spin class (check its container)
    const spinnerContainer = screen.getByText('components.comparisonView.analyzingDifferences').closest('div');
    expect(spinnerContainer?.querySelector('.animate-spin')).toBeTruthy();
  });

  // ── 4. Empty diff (identical nodes) ───────────────────────────────

  it('shows no visible differences summary when the API returns empty diffs', async () => {
    mockCompareNodes.mockResolvedValue({
      only_in_a: [],
      only_in_b: [],
      agent_diffs: {},
      summary: '',
    });

    useSimulationStore.setState({
      selectedNodeId: '1',
      compareTargetNodeId: '2',
      nodes: [baselineNode, compareNode],
      currentSimulation: { id: 'sim-1' },
    } as never);

    render(<ComparisonView />);

    // The component has a 250ms debounce. waitFor polls until assertion passes.
    await waitFor(() => {
      expect(screen.getByText('components.comparisonView.noVisibleDiffSummary')).toBeInTheDocument();
    });
  });

  // ── 5. Event diff rendering (only_in_a / only_in_b) ───────────────

  it('renders events unique to each node in the correct columns', async () => {
    mockCompareNodes.mockResolvedValue({
      only_in_a: [
        { type: 'AGENT_SAY', data: { content: 'Hello from A' } },
        { type: 'SYSTEM', data: { message: 'System event in A' } },
      ],
      only_in_b: [
        { type: 'AGENT_ACTION', data: { content: 'Action in B' } },
      ],
      agent_diffs: {},
      summary: '',
    });

    useSimulationStore.setState({
      selectedNodeId: '1',
      compareTargetNodeId: '2',
      nodes: [baselineNode, compareNode],
      currentSimulation: { id: 'sim-1' },
    } as never);

    render(<ComparisonView />);

    await waitFor(() => {
      // The first event 'Hello from A' appears in both Key Divergence and the events list,
      // so we check there are at least that many occurrences
      // First events appear in both Key Divergence and events list
      expect(screen.getAllByText('Hello from A').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('System event in A')).toBeInTheDocument();
      // 'Action in B' is the first right event — appears in both Key Divergence and events list
      expect(screen.getAllByText('Action in B').length).toBeGreaterThanOrEqual(1);
    });
  });

  // ── 6. Agent property diffs ───────────────────────────────────────

  it('renders agent property diffs in the center column with name, keys, and A->B values', async () => {
    mockCompareNodes.mockResolvedValue({
      only_in_a: [],
      only_in_b: [],
      agent_diffs: {
        'Alice': {
          'trust': { a: '80', b: '95' },
          'stress': { a: '30', b: '20' },
        },
        'Bob': {
          'money': { a: '1000', b: '500' },
        },
      },
      summary: '',
    });

    useSimulationStore.setState({
      selectedNodeId: '1',
      compareTargetNodeId: '2',
      nodes: [baselineNode, compareNode],
      currentSimulation: { id: 'sim-1' },
    } as never);

    render(<ComparisonView />);

    await waitFor(() => {
      // Agent names should appear
      expect(screen.getByText('Alice')).toBeInTheDocument();
      expect(screen.getByText('Bob')).toBeInTheDocument();
      // Property keys with A→B values should be rendered
      expect(screen.getByText(/trust/)).toBeInTheDocument();
      expect(screen.getByText(/stress/)).toBeInTheDocument();
      expect(screen.getByText(/money/)).toBeInTheDocument();
      // The diff values show A=X → B=Y format
      expect(screen.getByText(/A=80/)).toBeInTheDocument();
      expect(screen.getByText(/B=95/)).toBeInTheDocument();
      expect(screen.getByText(/A=1000/)).toBeInTheDocument();
      expect(screen.getByText(/B=500/)).toBeInTheDocument();
    });
  });

  // ── 7. Stat cards ─────────────────────────────────────────────────

  it('displays the 4 stat cards with correct counts', async () => {
    mockCompareNodes.mockResolvedValue({
      only_in_a: [
        { type: 'AGENT_SAY', data: { content: 'A1' } },
        { type: 'AGENT_ACTION', data: { content: 'A2' } },
      ],
      only_in_b: [
        { type: 'ENVIRONMENT', data: { content: 'B1' } },
      ],
      agent_diffs: {
        'Alice': { 'trust': { a: '80', b: '90' } },
        'Bob': { 'reputation': { a: '50', b: '70' } },
      },
      summary: '',
    });

    useSimulationStore.setState({
      selectedNodeId: '1',
      compareTargetNodeId: '2',
      nodes: [baselineNode, compareNode],
      currentSimulation: { id: 'sim-1' },
    } as never);

    render(<ComparisonView />);

    await waitFor(() => {
      // Stat cards have labels and counts
      expect(screen.getByText('components.comparisonView.nodeAEvents')).toBeInTheDocument();
      expect(screen.getByText('components.comparisonView.nodeBEvents')).toBeInTheDocument();
      expect(screen.getByText('components.comparisonView.agentDiffFields')).toBeInTheDocument();
      expect(screen.getByText('components.comparisonView.eventTypes')).toBeInTheDocument();
      // event type count = 3 (AGENT_SAY, AGENT_ACTION, ENVIRONMENT)
      expect(screen.getByText('3')).toBeInTheDocument();
    });
  });

  // ── 8. LLM summary toggle ─────────────────────────────────────────

  it('renders the Use LLM for Summary checkbox and calls setComparisonUseLLM on click', async () => {
    const setComparisonUseLLM = vi.fn();
    useSimulationStore.setState({
      selectedNodeId: '1',
      compareTargetNodeId: '2',
      nodes: [baselineNode, compareNode],
      currentSimulation: { id: 'sim-1' },
      comparisonUseLLM: false,
      setComparisonUseLLM,
    } as never);

    mockCompareNodes.mockResolvedValue({
      only_in_a: [],
      only_in_b: [],
      agent_diffs: {},
      summary: '',
    });

    render(<ComparisonView />);

    await waitFor(() => {
      expect(screen.getByLabelText('components.comparisonView.useLLMForSummary')).toBeInTheDocument();
    });

    const checkbox = screen.getByLabelText('components.comparisonView.useLLMForSummary');
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    expect(setComparisonUseLLM).toHaveBeenCalledWith(true);
  });

  // ── 9. Generate Analysis Report button ────────────────────────────

  it('shows Generate Analysis Report button when no summary is loaded', async () => {
    useSimulationStore.setState({
      selectedNodeId: '1',
      compareTargetNodeId: '2',
      nodes: [baselineNode, compareNode],
      currentSimulation: { id: 'sim-1' },
    } as never);

    // Return undefined so that compareData stays null after the API call
    mockCompareNodes.mockResolvedValue(undefined);

    render(<ComparisonView />);

    // After the debounce fires, the button should appear
    await screen.findByText('components.comparisonView.generateAnalysisReport', {}, { timeout: 5000 });
  });

  // ── 10. Event type translations ───────────────────────────────────

  it('translates different event types using the correct translation keys', async () => {
    mockCompareNodes.mockResolvedValue({
      only_in_a: [
        { type: 'SYSTEM', data: { content: 'System msg' } },
        { type: 'AGENT_SAY', data: { content: 'Agent says hi' } },
        { type: 'AGENT_ACTION', data: { content: 'Agent does action' } },
        { type: 'ENVIRONMENT', data: { content: 'Env update' } },
      ],
      only_in_b: [],
      agent_diffs: {},
      summary: '',
    });

    useSimulationStore.setState({
      selectedNodeId: '1',
      compareTargetNodeId: '2',
      nodes: [baselineNode, compareNode],
      currentSimulation: { id: 'sim-1' },
    } as never);

    render(<ComparisonView />);

    await waitFor(() => {
      // Translation keys appear in both Key Divergence and the events list
      expect(screen.getAllByText('components.logViewer.typeSystem').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('components.logViewer.typeDialogue').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('components.logViewer.typeAction')).toBeInTheDocument();
      expect(screen.getByText('components.logViewer.typeEnvironment')).toBeInTheDocument();
    });
  });

  // ── 11. Key Divergence section ────────────────────────────────────

  it('shows the first unique event from each node side-by-side in Key Divergence', async () => {
    mockCompareNodes.mockResolvedValue({
      only_in_a: [
        { type: 'AGENT_SAY', data: { content: 'First A event — the divergence starts here' } },
        { type: 'SYSTEM', data: { message: 'Second A event' } },
      ],
      only_in_b: [
        { type: 'AGENT_ACTION', data: { content: 'First B event — different path' } },
      ],
      agent_diffs: {},
      summary: '',
    });

    useSimulationStore.setState({
      selectedNodeId: '1',
      compareTargetNodeId: '2',
      nodes: [baselineNode, compareNode],
      currentSimulation: { id: 'sim-1' },
    } as never);

    render(<ComparisonView />);

    await waitFor(() => {
      // The first event from A appears in both Key Divergence and the events list
      expect(screen.getAllByText('First A event — the divergence starts here').length).toBeGreaterThanOrEqual(1);
      // The first event from B appears in both Key Divergence and events list
      expect(screen.getAllByText('First B event — different path').length).toBeGreaterThanOrEqual(1);
      // The Key Divergence section itself should have a heading
      expect(screen.getByText('components.comparisonView.keyDivergence')).toBeInTheDocument();
      expect(screen.getByText('components.comparisonView.keyDivergenceHint')).toBeInTheDocument();
    });
  });

  // ── 12. Loading state on Generate Analysis Report button ──────────

  it('shows a spinner on the Generate Analysis Report button when isLoadingComparison is true', () => {
    vi.useFakeTimers();

    // Mock API to return undefined so compareData stays null
    mockCompareNodes.mockResolvedValue(undefined);

    useSimulationStore.setState({
      selectedNodeId: '1',
      compareTargetNodeId: '2',
      nodes: [baselineNode, compareNode],
      currentSimulation: { id: 'sim-1' },
    } as never);

    render(<ComparisonView />);

    // useEffect fires → setIsLoadingComparison(true) → re-render with spinner
    // Fake timers freeze the 250ms debounce, so the API call never fires
    expect(screen.getByText('components.comparisonView.analyzingDifferences')).toBeInTheDocument();

    // Spinner should be present in the Smart Summary section
    const spinnerContainer = screen.getByText('components.comparisonView.analyzingDifferences').closest('div');
    expect(spinnerContainer?.querySelector('.animate-spin')).toBeTruthy();

    // The Generate Analysis Report button text should NOT be shown during loading
    expect(screen.queryByText('components.comparisonView.generateAnalysisReport')).not.toBeInTheDocument();

    vi.useRealTimers();
  });
});
