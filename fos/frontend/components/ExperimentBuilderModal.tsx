/**
 * Experiment Builder Modal Component
 *
 * Modal wrapper for the 5-step Experiment Builder.
 * Replaces the existing SimulationWizard with a more structured experiment creation flow.
 */

import React, { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useExperimentBuilder } from '../store/experiment-builder';
import { ExperimentBuilder } from './experiment/ExperimentBuilder';
import { X } from 'lucide-react';
import { useSimulationStore } from '../store';
import {
  buildScenarioTitle,
  getLocalizedScenarioDescription,
  getLocalizedScenarioName,
} from '../utils/scenarioLocalization';
import { isPolicyCascadeScenario } from '../utils/policyCascade';
import i18n from '../i18n';

interface ExperimentBuilderModalProps {
  isOpen?: boolean;
  onClose?: () => void;
  onComplete?: (config: unknown) => void;
  presentation?: 'modal' | 'page';
}

export function launchExperimentFromBuilderState({
  t,
  addSimulation,
  addNotification,
}: {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: any;
  addSimulation: (...args: any[]) => void;
  addNotification: ((type: string, message: string) => void) | undefined;
}) {
  const state = useExperimentBuilder.getState();
  const localizedScenarioName = getLocalizedScenarioName(t, state.selectedScenarioData);
  const localizedScenarioDescription = getLocalizedScenarioDescription(
    t,
    state.selectedScenarioData,
  );

  const scenarioName = localizedScenarioName || t('experimentBuilder.newExperiment');
  const scenarioDescription = state.scenarioDescription || '';

  const convertAgentToSimulationAgent = (agentType: any) => {
    const count = agentType.count || 1;
    const props = agentType.properties || {};
    const agents = [];

    for (let i = 0; i < count; i++) {
      const rolePrompt = agentType.rolePrompt?.trim() || null;
      const userProfile = agentType.userProfile?.trim() || '';
      const suffix = count > 1 ? ` ${i + 1}` : '';
      const idSuffix = count > 1 ? `-${i}` : '';
      const avatarUrl = props.avatarUrl as string ||
        `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(agentType.label || 'agent') + i}`;

      const providerId = agentType.providerId ?? state.selectedProviderId;
      const selectedProvider = state.llmProviders.find((provider) => provider.id === providerId);
      const llmConfig = selectedProvider
        ? {
            provider: selectedProvider.provider,
            model: selectedProvider.model || 'default',
          }
        : {
            provider: 'backend',
            model: 'default',
          };

      agents.push({
        name: agentType.label + suffix,
        id: agentType.id + idSuffix,
        role: rolePrompt || '',
        role_prompt: rolePrompt,
        profile: userProfile || '',
        user_profile: userProfile || '',
        avatarUrl,
        llm_config: llmConfig,
        llmConfig: llmConfig,
        provider_id: providerId,
        properties: {
          ...props,
          avatarUrl,
        },
        history: {},
        memory: [],
        knowledgeBase: [],
        score: 0,
      });
    }

    return agents;
  };

  const customAgents = state.agentTypes.flatMap(convertAgentToSimulationAgent);
  const allAvailableActions = state.availableActions || [];
  const selectedActionObjects = allAvailableActions.filter(
    (action: any) => state.selectedActionIds.includes(action.name)
  );
  const scenarioData = state.selectedScenarioData;
  const resolvedDescription =
    scenarioDescription && scenarioDescription.trim().length > 0
      ? scenarioDescription
      : localizedScenarioDescription || t('experimentBuilder.customExperiment');
  const isCustomScenario = state.selectedScenarioId === 'custom';
  const customTurnOrdering =
    state.roundVisibility === 'random'
      ? 'random_sequential'
      : state.roundVisibility === 'simultaneous'
        ? 'simultaneous'
        : 'sequential';
  const scenarioParameters = {
    ...(state.scenarioParams || {}),
    ...(isCustomScenario ? { custom_prompt: resolvedDescription, turn_ordering: customTurnOrdering } : {}),
  };

  const name = buildScenarioTitle(scenarioName, resolvedDescription);
  const genericConfig: any = {
    description: resolvedDescription,
    scenario_id: state.selectedScenarioId || 'custom',
    actions: selectedActionObjects.map((action: any) => ({
      name: action.name,
      description: action.description || action.name,
    })),
    parameters: scenarioParameters,
    round_visibility: state.roundVisibility || 'simultaneous',
  };

  const isPolicyCascade = isPolicyCascadeScenario(scenarioData);

  const isNewArchitecture = scenarioData?.category === 'game_theory' ||
    scenarioData?.category === 'discussion' ||
    scenarioData?.category === 'grid' ||
    scenarioData?.category === 'sociology' ||
    scenarioData?.category === 'social_deduction' ||
    scenarioData?.category === 'spatial' ||
    scenarioData?.category === 'generative_city' ||
    scenarioData?.category === 'custom';

  addSimulation(
    name,
    {
      id: 'experiment-template',
      name,
      description: resolvedDescription,
      category: (scenarioData?.category || 'custom') as string,
      sceneType: isPolicyCascade ? 'policy_cascade_scene' : isNewArchitecture ? 'experiment' : 'generic',
      agents: customAgents,
      defaultTimeConfig: {
        baseTime: new Date().toISOString(),
        unit: 'hour' as const,
        step: 1,
      },
      genericConfig,
      defaultNetwork: state.socialNetwork || {},
    },
    undefined,
    undefined,
  );

  addNotification?.('success', t('experimentBuilder.experimentCreated'));
}

export const ExperimentBuilderModal: React.FC<ExperimentBuilderModalProps> = ({
  isOpen,
  onClose,
  onComplete,
}) => {
  const { t } = useTranslation();

  // Use the main simulation store to manage modal state
  const isWizardOpen = useSimulationStore((state) => state.isWizardOpen);
  const toggleWizard = useSimulationStore((state) => state.toggleWizard);
  const addSimulation = useSimulationStore((state) => state.addSimulation);
  const addNotification = useSimulationStore((state) => state.addNotification);

  // Use prop if explicitly provided, otherwise use store state
  const useExplicitState = isOpen !== undefined;
  const isModalOpen = useExplicitState ? isOpen : isWizardOpen;

  // Reset experiment builder state when modal opens
  useEffect(() => {
    if (isModalOpen) {
      useExperimentBuilder.getState().reset();
    }
  }, [isModalOpen]);

  const handleClose = () => {
    if (onClose) {
      onClose();
    } else {
      toggleWizard(false);
    }
  };

  const handleComplete = () => {
    // Get experiment builder state
    const state = useExperimentBuilder.getState();

    // Create simulation name from scenario
    const scenarioName = state.selectedScenarioData?.name || t('experimentBuilder.newExperiment');
    const scenarioDescription = state.scenarioDescription || '';

    // Build a descriptive name
    let name = scenarioName;
    if (scenarioDescription) {
      // Truncate description if too long
      const maxDescLength = 30;
      const description = scenarioDescription.length > maxDescLength
        ? scenarioDescription.substring(0, maxDescLength) + '...'
        : scenarioDescription;
      name = `${scenarioName} - ${description}`;
    }

    // Convert agent types to simulation agent format
    const convertAgentToSimulationAgent = (agentType: any, index: number) => {
      const count = agentType.count || 1;
      const props = agentType.properties || {};
      const agents = [];

      for (let i = 0; i < count; i++) {
        // Only use rolePrompt if explicitly provided - let backend handle identity from name
        const rolePrompt = agentType.rolePrompt?.trim() || null;
        const userProfile = agentType.userProfile?.trim() || '';

        // Determine unique ID and name for each agent instance
        const suffix = count > 1 ? ` ${i + 1}` : '';
        const idSuffix = count > 1 ? `-${i}` : '';

        // Use avatarUrl from properties if available, otherwise generate one
        const avatarUrl = props.avatarUrl as string ||
          `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(agentType.label || 'agent') + i}`;

        // Get LLM config - use agent type's provider if set, otherwise use global selection
        const providerId = agentType.providerId ?? state.selectedProviderId;
        const selectedProvider = state.llmProviders.find((p) => p.id === providerId);
        const llmConfig = selectedProvider
          ? {
              provider: selectedProvider.provider,
              model: selectedProvider.model || 'default',
            }
          : {
              provider: 'backend',
              model: 'default',
            };

        agents.push({
          name: agentType.label + suffix,
          id: agentType.id + idSuffix,
          role: rolePrompt || '',
          role_prompt: rolePrompt,  // snake_case for backend
          profile: userProfile || '',  // Don't fall back to rolePrompt — avoids duplication with role_prompt
          user_profile: userProfile || '',  // snake_case for backend
          avatarUrl: avatarUrl,
          llmConfig: llmConfig,
          provider_id: providerId,  // Track which provider this agent uses
          properties: {
            ...props,
            avatarUrl: avatarUrl,  // Ensure avatarUrl is in properties
          },
          history: {},
          memory: [],
          knowledgeBase: [],
          score: 0,  // Initialize score for agents that need it
        });
      }

      return agents;
    };

    // Create custom agents array from agent types
    const customAgents = state.agentTypes.flatMap(convertAgentToSimulationAgent);

    // Build action list with full objects (including descriptions)
    const allAvailableActions = state.availableActions || [];
    const selectedActionObjects = allAvailableActions.filter(
      (a: any) => state.selectedActionIds.includes(a.name)
    );

    // Get scenario for backend
    const scenarioData = state.selectedScenarioData;

    // Resolve description: prefer user-edited, otherwise scenario default, then generic fallback
    const resolvedDescription =
      scenarioDescription && scenarioDescription.trim().length > 0
        ? scenarioDescription
        : scenarioData?.description || t('experimentBuilder.customExperiment');
    const isCustomScenario = state.selectedScenarioId === 'custom';
    const customTurnOrdering =
      state.roundVisibility === 'random'
        ? 'random_sequential'
        : state.roundVisibility === 'simultaneous'
          ? 'simultaneous'
          : 'sequential';
    const scenarioParameters = {
      ...(state.scenarioParams || {}),
      ...(isCustomScenario ? { custom_prompt: resolvedDescription, turn_ordering: customTurnOrdering } : {}),
    };

    // Build generic config with full action objects and parameters
    const genericConfig: any = {
      description: resolvedDescription,
      scenario_id: state.selectedScenarioId || 'custom',
      actions: selectedActionObjects.map((a: any) => ({
        name: a.name,
        description: a.description || a.name,
      })),
      parameters: scenarioParameters,
      round_visibility: state.roundVisibility || 'simultaneous',
      locale: i18n.language?.startsWith('zh') ? 'zh' : 'en',
    };

    // Determine scene type: policy cascade uses dedicated scene, otherwise experiment/generic
    const isPolicyCascade = isPolicyCascadeScenario(scenarioData);

    // Determine if this uses the new Three-Layer Architecture
    // (strategic_decisions or any scenario with structured actions)
    const isNewArchitecture = scenarioData?.category === 'game_theory' ||
      scenarioData?.category === 'discussion' ||
      scenarioData?.category === 'grid' ||
      scenarioData?.category === 'sociology' ||
      scenarioData?.category === 'social_deduction' ||
      scenarioData?.category === 'spatial' ||
      scenarioData?.category === 'generative_city' ||
      scenarioData?.category === 'custom';

    addSimulation(
      name,
      {
        id: 'experiment-template',
        name: name,
        description: resolvedDescription,
        category: scenarioData ? 'system' : 'custom',
        sceneType: isPolicyCascade ? 'policy_cascade_scene' : isNewArchitecture ? 'experiment' : 'generic',
        agents: customAgents,
        defaultTimeConfig: {
          baseTime: new Date().toISOString(),
          unit: 'hour' as const,
          step: 1,
        },
        genericConfig: genericConfig,
        defaultNetwork: state.socialNetwork || {},
      },
      undefined,
      undefined
    );

    addNotification('success', t('experimentBuilder.experimentCreated'));

    if (onComplete) {
      onComplete({});
    } else {
      handleClose();
    }
  };

  // Early return if modal should not be visible
  if (!isModalOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm" style={{ background: 'var(--ss-overlay)' }}>
      <div className="rounded-xl w-full max-w-5xl overflow-hidden flex flex-col max-h-[90vh]" style={{ background: 'var(--ss-surface)', border: '1px solid var(--ss-border)', boxShadow: 'var(--ss-shadow-3)', color: 'var(--ss-text)' }}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: '1px solid var(--ss-border)' }}>
          <h2 className="text-lg font-semibold" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.modalTitle')}
          </h2>
          <button
            onClick={handleClose}
            className="transition-colors"
            style={{ color: 'var(--ss-text-subtle)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--ss-text)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--ss-text-subtle)'; }}
            aria-label={t('experimentBuilder.close')}
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          <ExperimentBuilder
            onComplete={handleComplete}
            onCancel={handleClose}
          />
        </div>
      </div>
    </div>
  );
};

export default ExperimentBuilderModal;
