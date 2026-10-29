import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const navigateMock = vi.fn();
const applyThemeMock = vi.fn();
const resetMock = vi.fn();
const setCurrentStepMock = vi.fn();

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'createExperiment.entry.title': 'Create experiment',
        'createExperiment.entry.badge': 'Experiment Entry',
        'createExperiment.entry.subtitle': 'Choose how you want to start.',
        'createExperiment.entry.enter': 'Enter',
        'createExperiment.entry.footer': 'Footer text',
        'createExperiment.entry.standardFlow': 'Standard flow',
        'createExperiment.entry.aiAssisted': 'AI assisted',
        'createExperiment.entry.preset.title': 'Preset templates',
        'createExperiment.entry.preset.description': 'Preset description',
        'createExperiment.entry.custom.title': 'Custom experiment',
        'createExperiment.entry.custom.description': 'Custom description',
      };
      return translations[key] ?? key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('../../store/theme', () => ({
  useThemeStore: (selector: (state: { apply: () => void }) => unknown) => selector({ apply: applyThemeMock }),
}));

vi.mock('../../store/experiment-builder', () => ({
  useExperimentBuilder: () => ({
    reset: resetMock,
    setCurrentStep: setCurrentStepMock,
  }),
}));

vi.mock('../../store', () => ({
  useSimulationStore: (selector: (state: { addSimulation: () => void; addNotification: () => void; currentSimulation: null }) => unknown) =>
    selector({
      addSimulation: vi.fn(),
      addNotification: vi.fn(),
      currentSimulation: null,
    }),
}));

vi.mock('../../components/experiment/ExperimentBuilder', () => ({
  ExperimentBuilder: () => <div>standard builder</div>,
}));

vi.mock('../../components/ExperimentBuilderModal', () => ({
  launchExperimentFromBuilderState: vi.fn(),
}));

describe('CreateExperiment entry page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a transition page with preset and custom entry points', async () => {
    const { CreateExperimentPage } = await import('../../pages/CreateExperimentPage');

    render(
      <MemoryRouter initialEntries={['/simulations/create']}>
        <Routes>
          <Route path="/simulations/create" element={<CreateExperimentPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByText('Create experiment')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Preset templates/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Custom experiment/i })).toBeInTheDocument();
  });

  it('navigates to the preset template flow when the preset button is clicked', async () => {
    const { CreateExperimentPage } = await import('../../pages/CreateExperimentPage');

    render(
      <MemoryRouter initialEntries={['/simulations/create']}>
        <Routes>
          <Route path="/simulations/create" element={<CreateExperimentPage />} />
        </Routes>
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: /Preset templates/i }));

    expect(navigateMock).toHaveBeenCalledWith('/simulations/create/preset');
  });
});
