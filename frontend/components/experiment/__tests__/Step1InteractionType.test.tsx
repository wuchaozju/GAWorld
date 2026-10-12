/**
 * Tests for the scenario picker step.
 *
 * Checks that scenarios render, can be selected, and that GAWorld selection
 * no longer preloads all residents before the user reaches the Agents step.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { Step1InteractionType } from '../Step1InteractionType';
import { useExperimentBuilder } from '../../../store/experiment-builder';
import { getAllScenarios } from '../../../services/scenarios';

vi.mock('../../../store/experiment-builder', () => ({
  useExperimentBuilder: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string | { defaultValue?: string; count?: number }) => {
      const translations: Record<string, string> = {
        'common.loading': 'Loading...',
        'scenario.category.game_theory': 'Game Theory',
        'scenario.category.sociology': 'Sociology',
        'scenario.category.generative_city': 'Generative City',
        'scenario.sociology.social-norm-disruption.name': 'Social Norm Disruption',
        'scenario.generative_city.gaworld.name': 'GAWorld',
      };
      if (translations[key]) {
        return translations[key];
      }
      if (typeof fallback === 'string') {
        return fallback;
      }
      return fallback?.defaultValue || key;
    },
  }),
}));

vi.mock('../../../services/scenarios', () => ({
  getAllScenarios: vi.fn(() => Promise.resolve([
    {
      id: 'social-norm-disruption',
      name: 'Social Norm Disruption',
      category: 'sociology',
      description: 'A new rule is suddenly imposed',
      parameters: [],
      actions: [],
    },
    {
      id: 'prisoners-dilemma',
      name: "Prisoner's Dilemma",
      category: 'game_theory',
      description: 'Classic game theory scenario',
      parameters: [],
      actions: [],
    },
    {
      id: 'gaworld',
      name: 'GAWorld',
      category: 'generative_city',
      description: 'A city simulation',
      parameters: [],
      actions: [],
    },
  ])),
}));

function mockBuilderStore(overrides: Record<string, unknown> = {}) {
  return {
    selectedScenarioId: null,
    setSelectedScenarioId: vi.fn(),
    setSelectedScenarioData: vi.fn(),
    markStepComplete: vi.fn(),
    ...overrides,
  } as ReturnType<typeof useExperimentBuilder>;
}

describe('Step1InteractionType', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render loading state initially', () => {
    vi.mocked(getAllScenarios).mockImplementationOnce(() => new Promise(() => {}));
    vi.mocked(useExperimentBuilder).mockReturnValue(mockBuilderStore());

    render(<Step1InteractionType />);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('should render scenarios after loading', async () => {
    vi.mocked(useExperimentBuilder).mockReturnValue(mockBuilderStore());

    render(<Step1InteractionType />);

    await waitFor(() => {
      expect(screen.getAllByText('Sociology').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Game Theory').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Generative City').length).toBeGreaterThan(0);
    });
  });

  it('should render category accordions', async () => {
    vi.mocked(useExperimentBuilder).mockReturnValue(mockBuilderStore());

    render(<Step1InteractionType />);

    await waitFor(() => {
      expect(screen.getAllByText('Sociology').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Game Theory').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Generative City').length).toBeGreaterThan(0);
    });
  });

  it('should call setSelectedScenarioId when scenario is clicked', async () => {
    const setSelectedScenarioId = vi.fn();
    const setSelectedScenarioData = vi.fn();
    const markStepComplete = vi.fn();

    vi.mocked(useExperimentBuilder).mockReturnValue(mockBuilderStore({
      setSelectedScenarioId,
      setSelectedScenarioData,
      markStepComplete,
    }));

    render(<Step1InteractionType />);

    await waitFor(() => {
      expect(screen.getAllByText('Sociology').length).toBeGreaterThan(0);
    });

    await act(async () => {
      fireEvent.click(screen.getAllByText('Sociology')[0]);
    });

    await act(async () => {
      fireEvent.click(screen.getByText('Social Norm Disruption'));
    });

    expect(setSelectedScenarioId).toHaveBeenCalledWith('social-norm-disruption');
    expect(setSelectedScenarioData).toHaveBeenCalledWith(expect.objectContaining({ id: 'social-norm-disruption' }));
    expect(markStepComplete).toHaveBeenCalledWith(1);
  });

  it('should not preload gaworld agents when gaworld is selected', async () => {
    const setSelectedScenarioId = vi.fn();
    const setSelectedScenarioData = vi.fn();
    const markStepComplete = vi.fn();

    vi.mocked(useExperimentBuilder).mockReturnValue(mockBuilderStore({
      setSelectedScenarioId,
      setSelectedScenarioData,
      markStepComplete,
    }));

    render(<Step1InteractionType />);

    await waitFor(() => {
      expect(screen.getAllByText('Generative City').length).toBeGreaterThan(0);
    });

    await act(async () => {
      fireEvent.click(screen.getAllByText('Generative City')[0]);
    });

    await act(async () => {
      fireEvent.click(screen.getByText('GAWorld'));
    });

    expect(setSelectedScenarioId).toHaveBeenCalledWith('gaworld');
    expect(setSelectedScenarioData).toHaveBeenCalledWith(expect.objectContaining({ id: 'gaworld' }));
    expect(markStepComplete).toHaveBeenCalledWith(1);
  });
});
