/**
 * These tests make sure the GAWorld population picker shows the actual counts.
 *
 * - The first test checks that each card shows its resident count in the text.
 */

import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import * as matchers from '@testing-library/jest-dom/matchers';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { GAWorldPopulationChooser } from '../GAWorldPopulationChooser';

expect.extend(matchers);
afterEach(() => cleanup());

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'experimentBuilder.step4.gaworld.populationTitle': 'Population',
        'experimentBuilder.step4.gaworld.populationHint': 'Select a population configuration for the GA World scenario.',
        'experimentBuilder.step4.gaworld.populationOptionLabel': 'Population',
        'experimentBuilder.step4.gaworld.populationOptionStarter': 'Starter Population',
        'experimentBuilder.step4.gaworld.populationOptionFull': 'Full Population',
        'experimentBuilder.step4.gaworld.recommended': 'Recommended',
        'experimentBuilder.step4.gaworld.loadResidents': 'Load Residents',
      };

      return translations[key] ?? key;
    },
  }),
}));

describe('GAWorldPopulationChooser', () => {
  it('test_gaworld_population_cards_show_their_resident_counts', () => {
    render(
      <GAWorldPopulationChooser
        selectedCount={10}
        isLoading={false}
        onSelectCount={vi.fn()}
        onLoadResidents={vi.fn()}
      />,
    );

    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('10')).toBeInTheDocument();
    expect(screen.getByText('20')).toBeInTheDocument();
    expect(screen.getByText('50')).toBeInTheDocument();
  });
});
