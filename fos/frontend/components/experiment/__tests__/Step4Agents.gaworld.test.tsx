/**
 * Tests for the GAWorld population chooser in Step 4.
 *
 * Checks that GAWorld waits for a population choice before loading residents
 * and then requests the chosen cohort size.
 */

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import * as matchers from '@testing-library/jest-dom/matchers';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Step4Agents } from '../Step4Agents';
import { useExperimentBuilder } from '../../../store/experiment-builder';

expect.extend(matchers);

vi.mock('../../../store/experiment-builder', () => ({
  useExperimentBuilder: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string; count?: number }) => options?.defaultValue || key,
  }),
}));

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: () => ({
    getTotalSize: () => 0,
    getVirtualItems: () => [],
  }),
}));

vi.mock('../../wizard/Step2DemographicsEditor', () => ({
  Step2DemographicsEditor: () => <div />,
}));

vi.mock('../../../store/helpers', () => ({
  generateAgentsWithDemographics: vi.fn(),
  isZh: () => false,
}));

describe('Step4Agents GAWorld defaults', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('test_gaworld_step_four_shows_population_chooser_before_loading_agents', async () => {
    const loadDefaultAgentsForScenario = vi.fn(() => Promise.resolve());
    vi.mocked(useExperimentBuilder).mockReturnValue({
      agentMode: 'manual',
      setAgentMode: vi.fn(),
      agentTypes: [],
      addAgentType: vi.fn(),
      removeAgentType: vi.fn(),
      updateAgentType: vi.fn(),
      llmProviders: [],
      selectedProviderId: null,
      setSelectedProviderId: vi.fn(),
      scenarioParams: {},
      setScenarioParams: vi.fn(),
      loadProviders: vi.fn(),
      getSelectedProviderId: vi.fn(() => null),
      selectedScenarioId: 'gaworld',
      selectedScenarioData: {
        id: 'gaworld',
        name: 'GAWorld',
        category: 'generative_city',
        description: 'GAWorld',
        parameters: [],
        actions: [],
      },
      loadDefaultAgentsForScenario,
    } as ReturnType<typeof useExperimentBuilder>);

    render(<Step4Agents />);

    expect(screen.getByText('Choose starting population')).toBeInTheDocument();
    expect(screen.getByText(/GAWorld includes 50 residents/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Load residents' })).toBeInTheDocument();
    expect(loadDefaultAgentsForScenario).not.toHaveBeenCalled();
  });

  it('test_gaworld_step_four_loads_recommended_population_when_requested', async () => {
    const loadDefaultAgentsForScenario = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useExperimentBuilder).mockReturnValue({
      agentMode: 'manual',
      setAgentMode: vi.fn(),
      agentTypes: [],
      addAgentType: vi.fn(),
      removeAgentType: vi.fn(),
      updateAgentType: vi.fn(),
      llmProviders: [],
      selectedProviderId: null,
      setSelectedProviderId: vi.fn(),
      scenarioParams: {},
      setScenarioParams: vi.fn(),
      loadProviders: vi.fn(),
      getSelectedProviderId: vi.fn(() => null),
      selectedScenarioId: 'gaworld',
      selectedScenarioData: {
        id: 'gaworld',
        name: 'GAWorld',
        category: 'generative_city',
        description: 'GAWorld',
        parameters: [],
        actions: [],
      },
      loadDefaultAgentsForScenario,
    } as ReturnType<typeof useExperimentBuilder>);

    render(<Step4Agents />);

    fireEvent.click(screen.getByRole('button', { name: '10 residents' }));
    fireEvent.click(screen.getByRole('button', { name: 'Load residents' }));

    await waitFor(() => {
      expect(loadDefaultAgentsForScenario).toHaveBeenCalledTimes(1);
    });

    const [, agentIds] = loadDefaultAgentsForScenario.mock.calls[0];
    const selectedIds = String(agentIds).split(',');
    expect(loadDefaultAgentsForScenario).toHaveBeenCalledWith('gaworld', expect.any(String));
    expect(selectedIds).toHaveLength(10);
  });

  it('test_gaworld_step_four_loads_full_city_when_fifty_residents_are_selected', async () => {
    const loadDefaultAgentsForScenario = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useExperimentBuilder).mockReturnValue({
      agentMode: 'manual',
      setAgentMode: vi.fn(),
      agentTypes: [],
      addAgentType: vi.fn(),
      removeAgentType: vi.fn(),
      updateAgentType: vi.fn(),
      llmProviders: [],
      selectedProviderId: null,
      setSelectedProviderId: vi.fn(),
      scenarioParams: {},
      setScenarioParams: vi.fn(),
      loadProviders: vi.fn(),
      getSelectedProviderId: vi.fn(() => null),
      selectedScenarioId: 'gaworld',
      selectedScenarioData: {
        id: 'gaworld',
        name: 'GAWorld',
        category: 'generative_city',
        description: 'GAWorld',
        parameters: [],
        actions: [],
      },
      loadDefaultAgentsForScenario,
    } as ReturnType<typeof useExperimentBuilder>);

    render(<Step4Agents />);

    fireEvent.click(screen.getByRole('button', { name: '50 residents' }));
    fireEvent.click(screen.getByRole('button', { name: 'Load residents' }));

    await waitFor(() => {
      expect(loadDefaultAgentsForScenario).toHaveBeenCalledTimes(1);
    });

    const [, agentIds] = loadDefaultAgentsForScenario.mock.calls[0];
    expect(String(agentIds).split(',')).toHaveLength(50);
  });
});
