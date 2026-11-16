/**
 * Tests for the GAWorld scenario setup screen.
 *
 * They check that beginners get a dedicated GAWorld panel with city-system
 * controls, starter presets, and an advanced seed field instead of a long
 * raw parameter list.
 */

import React from 'react';
import { cleanup, render, screen, fireEvent } from '@testing-library/react';
import * as matchers from '@testing-library/jest-dom/matchers';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { Step2StarterTemplate } from '../Step2StarterTemplate';

expect.extend(matchers);
afterEach(() => cleanup());

const mockUseExperimentBuilder = vi.fn();

vi.mock('../../../store/experiment-builder', () => ({
  useExperimentBuilder: () => mockUseExperimentBuilder(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, string>) => {
      const translations: Record<string, string> = {
        'experimentBuilder.step2.configureTitle': `Configure ${params?.name ?? ''}`,
        'experimentBuilder.step2.configureSubtitle': 'Adjust the scenario settings',
        'experimentBuilder.step2.scenarioDescriptionLabel': 'Description',
        'experimentBuilder.step2.scenarioDescriptionPlaceholder': 'Describe the scenario',
        'experimentBuilder.gaworld.startingPointTitle': 'Starting point',
        'experimentBuilder.gaworld.startingPointHint': 'Choose a starter mode, then fine-tune the city systems below.',
        'experimentBuilder.gaworld.citySystemsTitle': 'City systems',
        'experimentBuilder.gaworld.advancedTitle': 'Advanced',
        'experimentBuilder.gaworld.seedLabel': 'Reproducibility seed',
        'experimentBuilder.gaworld.seedDescription': 'Use the same seed to repeat the same setup.',
        'experimentBuilder.gaworld.presets.fast.title': 'Fast',
        'experimentBuilder.gaworld.presets.fast.description': 'A lightweight city run for quick iteration.',
        'experimentBuilder.gaworld.presets.balanced.title': 'Balanced',
        'experimentBuilder.gaworld.presets.balanced.description': 'A middle ground between speed and city detail.',
        'experimentBuilder.gaworld.presets.full_fidelity.title': 'Full',
        'experimentBuilder.gaworld.presets.full_fidelity.description': 'The richest city run with the most detail.',
        'experimentBuilder.gaworld.groups.information.title': 'Information',
        'experimentBuilder.gaworld.groups.information.description': 'How much outside information moves through the city.',
        'experimentBuilder.gaworld.groups.daily_life.title': 'Daily Life',
        'experimentBuilder.gaworld.groups.daily_life.description': 'How fixed or flexible daily routines are.',
        'experimentBuilder.gaworld.groups.people.title': 'People',
        'experimentBuilder.gaworld.groups.people.description': 'How adaptive and human-like people behave.',
        'experimentBuilder.gaworld.groups.memory.title': 'Memory',
        'experimentBuilder.gaworld.groups.memory.description': 'How much people carry forward from previous days.',
        'experimentBuilder.gaworld.modes.information.off.title': 'Off',
        'experimentBuilder.gaworld.modes.information.off.description': 'People do not react to outside information sources.',
        'experimentBuilder.gaworld.modes.information.city_news.title': 'City news only',
        'experimentBuilder.gaworld.modes.information.city_news.description': 'People receive shared news without active seeking.',
        'experimentBuilder.gaworld.modes.information.active_flow.title': 'Active information flow',
        'experimentBuilder.gaworld.modes.information.active_flow.description': 'People receive shared news and actively seek more.',
        'experimentBuilder.gaworld.modes.daily_life.stable_routines.title': 'Stable routines',
        'experimentBuilder.gaworld.modes.daily_life.stable_routines.description': 'Daily plans mostly repeat with little variation.',
        'experimentBuilder.gaworld.modes.daily_life.some_variation.title': 'Some variation',
        'experimentBuilder.gaworld.modes.daily_life.some_variation.description': 'Daily life changes sometimes without becoming chaotic.',
        'experimentBuilder.gaworld.modes.daily_life.flexible_daily_life.title': 'Flexible daily life',
        'experimentBuilder.gaworld.modes.daily_life.flexible_daily_life.description': 'Plans shift often and leave room for more improvisation.',
        'experimentBuilder.gaworld.modes.people.simple_behavior.title': 'Simple behavior',
        'experimentBuilder.gaworld.modes.people.simple_behavior.description': 'People behave in a more basic and predictable way.',
        'experimentBuilder.gaworld.modes.people.adaptive_behavior.title': 'Adaptive behavior',
        'experimentBuilder.gaworld.modes.people.adaptive_behavior.description': 'People respond to their situation in a moderate way.',
        'experimentBuilder.gaworld.modes.people.rich_human_behavior.title': 'Rich human behavior',
        'experimentBuilder.gaworld.modes.people.rich_human_behavior.description': 'People show richer adaptation and human detail.',
        'experimentBuilder.gaworld.modes.memory.in_the_moment.title': 'In-the-moment',
        'experimentBuilder.gaworld.modes.memory.in_the_moment.description': 'People mostly act on the current day.',
        'experimentBuilder.gaworld.modes.memory.some_continuity.title': 'Some continuity',
        'experimentBuilder.gaworld.modes.memory.some_continuity.description': 'People carry some recent context forward.',
        'experimentBuilder.gaworld.modes.memory.rich_memory.title': 'Rich memory',
        'experimentBuilder.gaworld.modes.memory.rich_memory.description': 'People build stronger continuity across days.',
      };

      return translations[key] ?? key;
    },
  }),
}));

function gaworldStore(overrides: Record<string, unknown> = {}) {
  return {
    selectedScenarioData: {
      id: 'gaworld',
      name: 'GAWorld',
      category: 'generative_city',
      description: 'GAWorld',
      parameters: [
        { key: 'execution_profile', type: 'string', default: 'fast', ui_hint: 'select' },
        { key: 'information_mode', type: 'string', default: 'city_news', ui_hint: 'select' },
        { key: 'daily_life_mode', type: 'string', default: 'some_variation', ui_hint: 'select' },
        { key: 'people_mode', type: 'string', default: 'adaptive_behavior', ui_hint: 'select' },
        { key: 'memory_mode', type: 'string', default: 'some_continuity', ui_hint: 'select' },
        { key: 'seed', type: 'integer', default: 42, ui_hint: 'number' },
      ],
      actions: [],
    },
    scenarioDescription: 'GAWorld description',
    scenarioParams: {
      execution_profile: 'fast',
      information_mode: 'city_news',
      daily_life_mode: 'some_variation',
      people_mode: 'adaptive_behavior',
      memory_mode: 'some_continuity',
      seed: 42,
    },
    roundVisibility: 'simultaneous',
    turnOrder: 'fixed',
    setScenarioDescription: vi.fn(),
    setScenarioParams: vi.fn(),
    setRoundVisibility: vi.fn(),
    setTurnOrder: vi.fn(),
    loadDefaultAgentsForScenario: vi.fn(),
    ...overrides,
  };
}

describe('Step2StarterTemplate GAWorld', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the custom GAWorld city-system panel', () => {
    mockUseExperimentBuilder.mockReturnValue(gaworldStore());

    render(<Step2StarterTemplate />);

    expect(screen.getByText('Starting point')).toBeInTheDocument();
    expect(screen.getByText('City systems')).toBeInTheDocument();
    expect(screen.getByText('Information')).toBeInTheDocument();
    expect(screen.getByText('Daily Life')).toBeInTheDocument();
    expect(screen.getByText('People')).toBeInTheDocument();
    expect(screen.getByText('Memory')).toBeInTheDocument();
  });

  it('hides legacy raw fields and keeps seed in advanced only', () => {
    mockUseExperimentBuilder.mockReturnValue(gaworldStore());

    render(<Step2StarterTemplate />);

    expect(screen.queryByText('sim_days')).not.toBeInTheDocument();
    expect(screen.queryByText('agent_ids')).not.toBeInTheDocument();
    expect(screen.queryByText('intervention_enabled')).not.toBeInTheDocument();
    expect(screen.queryByText('Reproducibility seed')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Advanced' }));
    expect(screen.getByText('Reproducibility seed')).toBeInTheDocument();
  });

  it('updates city-system controls when a starter preset is selected', () => {
    const store = gaworldStore();
    mockUseExperimentBuilder.mockReturnValue(store);

    render(<Step2StarterTemplate />);

    fireEvent.click(screen.getByRole('button', { name: /Balanced/ }));

    expect(store.setScenarioParams).toHaveBeenCalledWith(
      expect.objectContaining({
        execution_profile: 'balanced',
        information_mode: 'city_news',
        daily_life_mode: 'some_variation',
        people_mode: 'adaptive_behavior',
        memory_mode: 'some_continuity',
      }),
    );
  });

  it('test_gaworld_empty_setup_uses_fast_city_system_defaults', () => {
    const store = gaworldStore({
      scenarioParams: {},
      setScenarioParams: vi.fn(),
    });
    mockUseExperimentBuilder.mockReturnValue(store);

    render(<Step2StarterTemplate />);

    expect(store.setScenarioParams).toHaveBeenCalledWith({
      execution_profile: 'fast',
      information_mode: 'off',
      daily_life_mode: 'stable_routines',
      people_mode: 'simple_behavior',
      memory_mode: 'in_the_moment',
      seed: 42,
    });
  });
});
