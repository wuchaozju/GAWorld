/**
 * This file checks the beginner-friendly GAWorld setup panel.
 *
 * - The first test checks that starter presets and city-system controls appear.
 * - The second test checks that choosing a preset updates the visible settings.
 */

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import GAWorldScenarioPanel from './GAWorldScenarioPanel';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, params?: { defaultValue?: string }) => params?.defaultValue ?? _key,
  }),
}));

describe('GAWorldScenarioPanel', () => {
  it('test_panel_shows_presets_and_city_system_controls', () => {
    render(
      <GAWorldScenarioPanel
        scenarioParams={{ execution_profile: 'fast' }}
        setScenarioParams={vi.fn()}
      />,
    );

    expect(screen.getByText('Starting point')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Fast/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Balanced/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Full/i })).toBeInTheDocument();
    expect(screen.getByText('Information')).toBeInTheDocument();
    expect(screen.getByText('Daily Life')).toBeInTheDocument();
    expect(screen.getByText('People')).toBeInTheDocument();
    expect(screen.getByText('Memory')).toBeInTheDocument();
  });

  it('test_full_preset_updates_all_city_modes', () => {
    const setScenarioParams = vi.fn();
    render(
      <GAWorldScenarioPanel
        scenarioParams={{ execution_profile: 'fast', seed: 42 }}
        setScenarioParams={setScenarioParams}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Full/i }));

    expect(setScenarioParams).toHaveBeenCalledWith({
      execution_profile: 'full_fidelity',
      seed: 42,
      information_mode: 'active_flow',
      daily_life_mode: 'flexible_daily_life',
      people_mode: 'rich_human_behavior',
      memory_mode: 'rich_memory',
    });
  });
});
