/**
 * Tests for Step3Scenario component - dynamic actions generation.
 *
 * Tests for:
 * - Dynamic actions generation from generates_actions parameter
 * - Info message display when actions are dynamically generated
 * - Static actions fallback when no generates_actions parameter exists
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { Step3Scenario } from '../Step3Scenario';
import { useExperimentBuilder } from '@/store/experiment-builder';
import { vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
    const translations: Record<string, string> = {
      'experimentBuilder.actions.chooseAction': `Choose ${params?.action || ''}`,
      'experimentBuilder.dynamicActionsInfo.title': 'Dynamic Actions:',
      'experimentBuilder.dynamicActionsInfo.message':
        'These actions are generated from the parameter. Edit it in Step 2 to change the available choices.',
      'experimentBuilder.step3.noActions': 'No actions available. Please select a scenario first',
    };
    let result = translations[key] || String(params?.defaultValue ?? key);
    if (params) {
      Object.keys(params).forEach((param) => {
        result = result.replace(`{${param}}`, String(params[param]));
      });
    }
    return result;
  },
  }),
}));

const wrapper = ({ children }: { children: React.ReactNode }) => <>{children}</>;

// Mock the store
vi.mock('@/store/experiment-builder', () => ({
  useExperimentBuilder: vi.fn(),
}));

describe('Step3Scenario - Dynamic Actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // =========================================================================
  // Dynamic Actions Generation Tests
  // =========================================================================

  describe('Dynamic Actions Generation', () => {
    test('should generate actions from choices parameter when generates_actions is true', async () => {
      const mockSetAvailableActions = vi.fn();
      const mockSetSelectedActionIds = vi.fn();

      const mockStore = {
        selectedScenarioData: {
          id: 'coordination_game',
          name: 'Coordination Game',
          parameters: [
            {
              id: 'choices',
              key: 'choices',
              label: 'Available Choices',
              type: 'string',
              default: 'red, blue, green',
              ui_hint: 'text',
              generates_actions: true,
            },
          ],
          actions: [],
        },
        scenarioParams: { choices: 'yes, no, maybe' },
        availableActions: [],
        selectedActionIds: [],
        setAvailableActions: mockSetAvailableActions,
        setSelectedActionIds: mockSetSelectedActionIds,
        toggleActionId: vi.fn(),
        validationErrors: {},
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      await waitFor(() => {
        // Verify setAvailableActions was called with generated actions
        expect(mockSetAvailableActions).toHaveBeenCalledWith(
          expect.arrayContaining([
            expect.objectContaining({ name: 'yes', description: expect.stringContaining('yes') }),
            expect.objectContaining({ name: 'no', description: expect.stringContaining('no') }),
            expect.objectContaining({ name: 'maybe', description: expect.stringContaining('maybe') }),
          ])
        );
      });
    });

    test('should generate actions from default value when scenarioParams is empty', async () => {
      const mockSetAvailableActions = vi.fn();
      const mockSetSelectedActionIds = vi.fn();

      const mockStore = {
        selectedScenarioData: {
          id: 'coordination_game',
          name: 'Coordination Game',
          parameters: [
            {
              id: 'choices',
              key: 'choices',
              label: 'Available Choices',
              type: 'string',
              default: 'A, B, C',
              ui_hint: 'text',
              generates_actions: true,
            },
          ],
          actions: [],
        },
        scenarioParams: {}, // Empty params - should use default
        availableActions: [],
        selectedActionIds: [],
        setAvailableActions: mockSetAvailableActions,
        setSelectedActionIds: mockSetSelectedActionIds,
        toggleActionId: vi.fn(),
        validationErrors: {},
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      await waitFor(() => {
        // Verify setAvailableActions was called with default value actions
        expect(mockSetAvailableActions).toHaveBeenCalledWith(
          expect.arrayContaining([
            expect.objectContaining({ name: 'A' }),
            expect.objectContaining({ name: 'B' }),
            expect.objectContaining({ name: 'C' }),
          ])
        );
      });
    });

    test('should handle empty choices string gracefully', async () => {
      const mockSetAvailableActions = vi.fn();
      const mockSetSelectedActionIds = vi.fn();

      const mockStore = {
        selectedScenarioData: {
          id: 'coordination_game',
          name: 'Coordination Game',
          parameters: [
            {
              id: 'choices',
              key: 'choices',
              label: 'Available Choices',
              type: 'string',
              default: '',
              ui_hint: 'text',
              generates_actions: true,
            },
          ],
          actions: [],
        },
        scenarioParams: { choices: '' },
        availableActions: [],
        selectedActionIds: [],
        setAvailableActions: mockSetAvailableActions,
        setSelectedActionIds: mockSetSelectedActionIds,
        toggleActionId: vi.fn(),
        validationErrors: {},
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      await waitFor(() => {
        // Should be called with empty array
        expect(mockSetAvailableActions).toHaveBeenCalledWith([]);
      });
    });
  });

  // =========================================================================
  // Info Message Display Tests
  // =========================================================================

  describe('Info Message Display', () => {
    test('should show dynamic actions info message when actions are generated', () => {
      const mockStore = {
        selectedScenarioData: {
          id: 'coordination_game',
          name: 'Coordination Game',
          parameters: [
            {
              id: 'choices',
              key: 'choices',
              label: 'Available Choices',
              type: 'string',
              default: 'red, blue, green',
              ui_hint: 'text',
              generates_actions: true,
            },
          ],
          actions: [],
        },
        scenarioParams: { choices: 'A, B' },
        availableActions: [
          { name: 'A', description: 'Choose A' },
          { name: 'B', description: 'Choose B' },
        ],
        selectedActionIds: ['A', 'B'],
        setAvailableActions: vi.fn(),
        setSelectedActionIds: vi.fn(),
        toggleActionId: vi.fn(),
        validationErrors: {},
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      // Check for dynamic actions info message
      expect(screen.getByText(/Dynamic Actions:/i)).toBeInTheDocument();
    });

    test('should NOT show dynamic actions info message when no generates_actions parameter', () => {
      const mockStore = {
        selectedScenarioData: {
          id: 'prisoners_dilemma',
          name: "Prisoner's Dilemma",
          parameters: [],
          actions: [
            { id: 'cooperate', name: 'Cooperate', description: 'Cooperate with partner' },
            { id: 'defect', name: 'Defect', description: 'Betray partner' },
          ],
        },
        scenarioParams: {},
        availableActions: [
          { name: 'Cooperate', description: 'Cooperate with partner' },
          { name: 'Defect', description: 'Betray partner' },
        ],
        selectedActionIds: ['Cooperate', 'Defect'],
        setAvailableActions: vi.fn(),
        setSelectedActionIds: vi.fn(),
        toggleActionId: vi.fn(),
        validationErrors: {},
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      // Should NOT show dynamic actions info message
      expect(screen.queryByText(/Dynamic Actions:/i)).not.toBeInTheDocument();
    });
  });

  // =========================================================================
  // Static Actions Tests
  // =========================================================================

  describe('Static Actions Fallback', () => {
    test('should use static actions when no generates_actions parameter exists', async () => {
      const mockSetAvailableActions = vi.fn();
      const mockSetSelectedActionIds = vi.fn();

      const mockStore = {
        selectedScenarioData: {
          id: 'prisoners_dilemma',
          name: "Prisoner's Dilemma",
          parameters: [],
          actions: [
            { id: 'cooperate', name: 'Cooperate', description: 'Cooperate with partner' },
            { id: 'defect', name: 'Defect', description: 'Betray partner' },
          ],
        },
        scenarioParams: {},
        availableActions: [],
        selectedActionIds: [],
        setAvailableActions: mockSetAvailableActions,
        setSelectedActionIds: mockSetSelectedActionIds,
        toggleActionId: vi.fn(),
        validationErrors: {},
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      await waitFor(() => {
        // Should use static actions
        expect(mockSetAvailableActions).toHaveBeenCalledWith(
          expect.arrayContaining([
            expect.objectContaining({ name: 'Cooperate' }),
            expect.objectContaining({ name: 'Defect' }),
          ])
        );
      });
    });

    test('should use category_actions when available', async () => {
      const mockSetAvailableActions = vi.fn();
      const mockSetSelectedActionIds = vi.fn();

      const mockStore = {
        selectedScenarioData: {
          id: 'some_scenario',
          name: 'Some Scenario',
          category: 'game_theory',
          parameters: [],
          actions: [
            { id: 'basic_action', name: 'Basic Action', description: 'A basic action' },
          ],
          category_actions: [
            { id: 'cat_action1', name: 'Category Action 1', description: 'Category action 1' },
            { id: 'cat_action2', name: 'Category Action 2', description: 'Category action 2' },
          ],
        },
        scenarioParams: {},
        availableActions: [],
        selectedActionIds: [],
        setAvailableActions: mockSetAvailableActions,
        setSelectedActionIds: mockSetSelectedActionIds,
        toggleActionId: vi.fn(),
        validationErrors: {},
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      await waitFor(() => {
        // Should use category_actions, not scenario.actions
        expect(mockSetAvailableActions).toHaveBeenCalledWith(
          expect.arrayContaining([
            expect.objectContaining({ name: 'Category Action 1' }),
            expect.objectContaining({ name: 'Category Action 2' }),
          ])
        );
      });
    });

    test('should replace policy scene actions with policy-specific action set', async () => {
      const mockSetAvailableActions = vi.fn();
      const mockSetSelectedActionIds = vi.fn();

      const mockStore = {
        selectedScenarioData: {
          id: 'policy_diffusion',
          name: 'Policy Diffusion',
          sceneType: 'policy_cascade_scene',
          parameters: [],
          actions: [
            { id: 'talk_to', name: 'talk_to', description: 'Irrelevant action' },
            { id: 'move', name: 'move', description: 'Irrelevant action' },
          ],
        },
        scenarioParams: {},
        availableActions: [],
        selectedActionIds: [],
        setAvailableActions: mockSetAvailableActions,
        setSelectedActionIds: mockSetSelectedActionIds,
        toggleActionId: vi.fn(),
        validationErrors: {},
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      await waitFor(() => {
        expect(mockSetAvailableActions).toHaveBeenCalledWith(
          expect.arrayContaining([
            expect.objectContaining({ name: 'send_message' }),
            expect.objectContaining({ name: 'yield' }),
            expect.objectContaining({ name: 'report_upward' }),
            expect.objectContaining({ name: 'escalate_complaint' }),
            expect.objectContaining({ name: 'consult_peer' }),
            expect.objectContaining({ name: 'notify_subordinate' }),
            expect.objectContaining({ name: 'announce_policy_adjustment' }),
          ])
        );
      });

      await waitFor(() => {
        expect(mockSetSelectedActionIds).toHaveBeenCalledWith([
          'send_message',
          'yield',
          'report_upward',
          'escalate_complaint',
          'consult_peer',
          'notify_subordinate',
          'announce_policy_adjustment',
        ]);
      });
    });

    test('should detect backend policy_erosion scenario and use policy-specific action set', async () => {
      const mockSetAvailableActions = vi.fn();
      const mockSetSelectedActionIds = vi.fn();

      const mockStore = {
        selectedScenarioData: {
          id: 'policy_erosion',
          name: 'Policy Meaning Erosion',
          parameters: [
            { key: 'cascade_mode', label: 'Cascade Mode', type: 'string', default: 'strict_cascade' },
          ],
          actions: [],
          category_actions: [
            { id: 'comply_publicly', name: 'comply_publicly', description: 'Irrelevant generic action' },
          ],
        },
        scenarioParams: {},
        availableActions: [],
        selectedActionIds: [],
        setAvailableActions: mockSetAvailableActions,
        setSelectedActionIds: mockSetSelectedActionIds,
        toggleActionId: vi.fn(),
        validationErrors: {},
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      await waitFor(() => {
        expect(mockSetAvailableActions).toHaveBeenCalledWith(
          expect.arrayContaining([
            expect.objectContaining({ name: 'report_upward' }),
            expect.objectContaining({ name: 'consult_peer' }),
            expect.objectContaining({ name: 'announce_policy_adjustment' }),
          ])
        );
      });
    });

    test('should only expose speak and skip for custom scenario', async () => {
      const mockSetAvailableActions = vi.fn();
      const mockSetSelectedActionIds = vi.fn();

      const mockStore = {
        selectedScenarioData: {
          id: 'custom',
          name: 'Custom Scenario',
          category: 'custom',
          parameters: [],
          actions: [
            { id: 'speak', name: 'Speak', description: 'Say something to the group' },
            { id: 'skip', name: 'Skip', description: 'Pass without speaking this turn' },
          ],
          default_action_ids: ['speak', 'skip'],
        },
        scenarioParams: {},
        availableActions: [],
        selectedActionIds: [],
        setAvailableActions: mockSetAvailableActions,
        setSelectedActionIds: mockSetSelectedActionIds,
        toggleActionId: vi.fn(),
        validationErrors: {},
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      await waitFor(() => {
        expect(mockSetAvailableActions).toHaveBeenCalledWith([
          { id: 'speak', name: 'Speak', description: 'Say something to the group' },
          { id: 'skip', name: 'Skip', description: 'Pass without speaking this turn' },
        ]);
      });

      await waitFor(() => {
        expect(mockSetSelectedActionIds).toHaveBeenCalledWith(['Speak', 'Skip']);
      });

      expect(screen.queryByText('experimentBuilder.step3.addCustomAction')).not.toBeInTheDocument();
    });
  });

  // =========================================================================
  // Action Selection Tests
  // =========================================================================

  describe('Action Selection', () => {
    test('should select all generated actions by default', async () => {
      const mockSetAvailableActions = vi.fn();
      const mockSetSelectedActionIds = vi.fn();

      const mockStore = {
        selectedScenarioData: {
          id: 'coordination_game',
          name: 'Coordination Game',
          parameters: [
            {
              id: 'choices',
              key: 'choices',
              label: 'Available Choices',
              type: 'string',
              default: '',
              ui_hint: 'text',
              generates_actions: true,
            },
          ],
          actions: [],
        },
        scenarioParams: { choices: 'Option1, Option2, Option3' },
        availableActions: [],
        selectedActionIds: [],
        setAvailableActions: mockSetAvailableActions,
        setSelectedActionIds: mockSetSelectedActionIds,
        toggleActionId: vi.fn(),
        validationErrors: {},
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      await waitFor(() => {
        // All actions should be selected by default
        expect(mockSetSelectedActionIds).toHaveBeenCalledWith(
          expect.arrayContaining(['Option1', 'Option2', 'Option3'])
        );
      });
    });
  });

  // =========================================================================
  // Rendering Tests
  // =========================================================================

  describe('Rendering', () => {
    test('should render action toggle cards', () => {
      const mockStore = {
        selectedScenarioData: {
          id: 'test_scenario',
          name: 'Test Scenario',
          parameters: [],
          actions: [
            { id: 'action1', name: 'Action One', description: 'First action' },
            { id: 'action2', name: 'Action Two', description: 'Second action' },
          ],
        },
        scenarioParams: {},
        availableActions: [
          { name: 'Action One', description: 'First action' },
          { name: 'Action Two', description: 'Second action' },
        ],
        selectedActionIds: ['Action One', 'Action Two'],
        setAvailableActions: vi.fn(),
        setSelectedActionIds: vi.fn(),
        toggleActionId: vi.fn(),
        validationErrors: {},
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      expect(screen.getByText('Action One')).toBeInTheDocument();
      expect(screen.getByText('Action Two')).toBeInTheDocument();
    });

    test('should show empty state when no actions available', () => {
      const mockStore = {
        selectedScenarioData: null,
        scenarioParams: {},
        availableActions: [],
        selectedActionIds: [],
        setAvailableActions: vi.fn(),
        setSelectedActionIds: vi.fn(),
        toggleActionId: vi.fn(),
        validationErrors: {},
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      expect(
        screen.getByText(/No actions available. Please select a scenario first/)
      ).toBeInTheDocument();
    });

    test('should show validation error when present', () => {
      const mockStore = {
        selectedScenarioData: {
          id: 'test_scenario',
          name: 'Test Scenario',
          parameters: [],
          actions: [],
        },
        scenarioParams: {},
        availableActions: [],
        selectedActionIds: [],
        setAvailableActions: vi.fn(),
        setSelectedActionIds: vi.fn(),
        toggleActionId: vi.fn(),
        validationErrors: { actions: 'Please select at least one action' },
      };

      vi.mocked(useExperimentBuilder).mockImplementation((selector?: any) => selector ? selector(mockStore as any) : mockStore as any);

      render(<Step3Scenario />, { wrapper });

      expect(screen.getByText('Please select at least one action')).toBeInTheDocument();
    });
  });
});
