/**
 * Tests for Step2StarterTemplate deduction configuration via ResourceConfig.
 *
 * Tests for:
 * - Public Goods scenario renders ResourceConfig with deduction_* parameters
 * - Budget, cost ratio, and anonymous mode fields are visible
 * - Deduction terminology matches backend contract (deduction_*, not punishment_*)
 *
 * The component renders ResourceConfig directly (no collapsible wrapper).
 * All fields are immediately visible.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { Step2StarterTemplate } from '../Step2StarterTemplate';

// Deduction-related translations (matching backend terminology)
const translations: Record<string, string> = {
  'experimentBuilder.deductionSettings.title': 'Deduction Settings',
  'experimentBuilder.deductionSettings.budgetLabel': 'Deduction Budget per Phase',
  'experimentBuilder.deductionSettings.budgetHint': 'Set to 0 to disable',
  'experimentBuilder.deductionSettings.costRatioLabel': 'Cost Ratio',
  'experimentBuilder.deductionSettings.costRatioHint': 'Higher values = stronger effect',
  'experimentBuilder.deductionSettings.anonymousLabel': 'Anonymous Deduction Mode',
  'experimentBuilder.resourceConfig.resourceNameLabel': 'Resource Name',
  'experimentBuilder.resourceConfig.amountPerRoundLabel': 'Amount per Round',
  'experimentBuilder.resourceConfig.multiplierLabel': 'Multiplier',
  'experimentBuilder.resourceConfig.resourceOptions.tokens': 'tokens',
  'experimentBuilder.resourceConfig.displaySettingsTitle': 'Display Settings',
  'experimentBuilder.step2.configureTitle': 'Configure {{name}}',
  'experimentBuilder.step2.configureSubtitle': 'Adjust the scenario settings',
  'experimentBuilder.step2.scenarioDescriptionLabel': 'Description',
  'experimentBuilder.step2.scenarioDescriptionPlaceholder': 'Describe the scenario',
  'experimentBuilder.step2.parametersTitle': 'Parameters',
};

// Mock react-i18next at module level
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, any>) => {
      let result = translations[key] ?? key;
      if (params) {
        Object.entries(params).forEach(([k, v]) => {
          result = result.replace(`{{${k}}}`, String(v));
        });
      }
      return result;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: '3rdParty', init: vi.fn() },
}));

// Mock the experiment builder store
const mockUseExperimentBuilder = vi.fn();
vi.mock('@/store/experiment-builder', () => ({
  useExperimentBuilder: () => mockUseExperimentBuilder(),
}));

function publicGoodsStore(overrides: Record<string, any> = {}) {
  return {
    selectedScenarioData: {
      id: 'public_goods',
      name: 'Public Goods Game',
      category: 'game_theory',
      description: 'A public goods game',
      parameters: [
        { key: 'resource_name', type: 'string', default: 'tokens', category: 'resource' },
        { key: 'tokens_per_round', type: 'number', default: 10, category: 'resource' },
        { key: 'multiplier', type: 'number', default: 1.3, category: 'resource' },
        { key: 'deduction_budget_per_phase', type: 'number', default: 0, category: 'deduction' },
        { key: 'deduction_cost_ratio', type: 'number', default: 3.0, category: 'deduction' },
        { key: 'deduction_anonymous', type: 'boolean', default: false, category: 'deduction' },
        { key: 'show_average_contribution', type: 'boolean', default: false, category: 'display' },
      ],
      actions: [],
    },
    scenarioDescription: 'Test',
    scenarioParams: {},
    roundVisibility: 'simultaneous',
    turnOrder: 'fixed',
    setScenarioDescription: vi.fn(),
    setScenarioParams: vi.fn(),
    setRoundVisibility: vi.fn(),
    setTurnOrder: vi.fn(),
    ...overrides,
  };
}

describe('Step2StarterTemplate - Deduction Configuration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Deduction Section Rendering', () => {
    it('should render deduction settings heading for public_goods scenario', () => {
      mockUseExperimentBuilder.mockReturnValue(publicGoodsStore());

      render(<Step2StarterTemplate />);

      expect(screen.getByText('Deduction Settings')).toBeInTheDocument();
    });

    it('should render deduction budget field with deduction_budget_per_phase label', () => {
      mockUseExperimentBuilder.mockReturnValue(publicGoodsStore());

      render(<Step2StarterTemplate />);

      expect(screen.getByText('Deduction Budget per Phase')).toBeInTheDocument();
    });

    it('should render cost ratio field with deduction_cost_ratio label', () => {
      mockUseExperimentBuilder.mockReturnValue(publicGoodsStore());

      render(<Step2StarterTemplate />);

      expect(screen.getByText('Cost Ratio')).toBeInTheDocument();
    });

    it('should render anonymous deduction toggle with deduction_anonymous label', () => {
      mockUseExperimentBuilder.mockReturnValue(publicGoodsStore());

      render(<Step2StarterTemplate />);

      expect(screen.getByText('Anonymous Deduction Mode')).toBeInTheDocument();
    });

    it('should not render deduction fields for non-public_goods scenarios', () => {
      mockUseExperimentBuilder.mockReturnValue(publicGoodsStore({
        selectedScenarioData: {
          id: 'prisoners_dilemma',
          name: "Prisoner's Dilemma",
          category: 'game_theory',
          description: 'A PD game',
          parameters: [],
          display_type: 'payoff_matrix',
          actions: [
            { id: 'cooperate', name: 'cooperate' },
            { id: 'defect', name: 'defect' },
          ],
        },
      }));

      render(<Step2StarterTemplate />);

      expect(screen.queryByText('Deduction Settings')).not.toBeInTheDocument();
    });

    it('should not render any punishment_* terminology', () => {
      mockUseExperimentBuilder.mockReturnValue(publicGoodsStore());

      render(<Step2StarterTemplate />);

      // No punishment-related text should appear anywhere in the rendered output
      expect(screen.queryByText(/punishment/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/punisher/i)).not.toBeInTheDocument();
    });
  });
});
