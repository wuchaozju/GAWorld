/**
 * This file runs the guided preset experiment builder.
 *
 * CreateExperimentPresetPage restores requested builder state, loads a linked scenario,
 * launches the finished simulation, and optionally saves a personal template.
 */

import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { useThemeStore } from '../store/theme';
import { useExperimentBuilder } from '../store/experiment-builder';
import { useSimulationStore } from '../store';
import { getAllScenarios } from '../services/scenarios';
import { ExperimentBuilder } from '../components/experiment/ExperimentBuilder';
import { launchExperimentFromBuilderState } from '../services/launchExperiment';
import {
  createExperimentTemplate,
  getActionType,
  type CreateTemplateRequest,
} from '../services/experiment-templates';
import "../styles/routes/experiment-setup.css";

type BuilderLocationState = {
  preserveBuilderState?: boolean;
  startStep?: 1 | 2 | 3 | 4 | 5 | 6;
  sourceFlow?: 'research-custom';
};

export function CreateExperimentPresetPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const applyTheme = useThemeStore((state) => state.apply);
  const addSimulation = useSimulationStore((state) => state.addSimulation);
  const addNotification = useSimulationStore((state) => state.addNotification);
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);

  const {
    reset,
    setCurrentStep,
    setSelectedScenarioId,
    setSelectedScenarioData,
  } = useExperimentBuilder();

  const [isLaunching, setIsLaunching] = useState(false);
  const previousSimulationIdRef = useRef<string | null>(currentSimulation?.id ?? null);
  const builderLocationState = (location.state || {}) as BuilderLocationState;
  const preserveBuilderState = Boolean(builderLocationState.preserveBuilderState);
  const startStep = builderLocationState.startStep ?? 1;
  const sourceFlow = builderLocationState.sourceFlow;
  const scenarioId = searchParams.get('scenario');

  useEffect(() => {
    applyTheme();
  }, [applyTheme]);

  useEffect(() => {
    if (preserveBuilderState) {
      setCurrentStep(startStep);
      return;
    }

    reset();
    setCurrentStep(1);
  }, [preserveBuilderState, reset, setCurrentStep, startStep]);

  useEffect(() => {
    if (!scenarioId || preserveBuilderState) return;

    let cancelled = false;

    const loadScenario = async () => {
      try {
        const scenarios = await getAllScenarios();
        if (cancelled) return;

        const selectedScenario = scenarios.find((scenario) => scenario.id === scenarioId);
        if (!selectedScenario) return;

        setSelectedScenarioId(selectedScenario.id);
        setSelectedScenarioData(selectedScenario);
      } catch {
        if (!cancelled) {
          // Keep the builder usable even if the scenario lookup fails.
        }
      }
    };

    void loadScenario();

    return () => {
      cancelled = true;
    };
  }, [preserveBuilderState, scenarioId, setSelectedScenarioData, setSelectedScenarioId]);

  useEffect(() => {
    if (!isLaunching) return;
    if (!currentSimulation?.id) return;
    if (currentSimulation.id === previousSimulationIdRef.current) return;
    navigate(`/simulations/${currentSimulation.id}`);
  }, [currentSimulation?.id, isLaunching, navigate]);

  const handleLaunch = () => {
    previousSimulationIdRef.current = currentSimulation?.id ?? null;
    setIsLaunching(true);
    launchExperimentFromBuilderState({ t, addSimulation, addNotification });
    void persistPersonalTemplateFromBuilderState();
  };

  const persistPersonalTemplateFromBuilderState = async () => {
    const state = useExperimentBuilder.getState();
    if (!state.scenarioParams?.ai_scientist_save_template) return;

    const selectedActions = (state.availableActions || []).filter((action) =>
      state.selectedActionIds.includes(action.name),
    );
    if (selectedActions.length === 0) return;

    const name = String(
      state.scenarioParams.ai_scientist_template_name ||
      state.selectedScenarioData?.name ||
      t('createExperiment.customBuilder.scenarioName', { defaultValue: 'Custom AI-generated scenario' }),
    ).trim();
    const description = String(state.scenarioDescription || state.selectedScenarioData?.description || '').trim();
    const {
      ai_scientist_save_template,
      ai_scientist_template_name,
      ...persistedSettings
    } = (state.scenarioParams || {}) as Record<string, unknown>;

    const templatePayload: CreateTemplateRequest = {
      name,
      description,
      actions: selectedActions.map((action) => {
        const actionType = getActionType(action.name);
        return {
          action_type: actionType,
          name: action.name,
          description: action.description || action.name,
          ...(actionType === 'custom' ? { custom_action_name: action.name } : {}),
        };
      }),
      settings: {
        scenario_id: String(state.selectedScenarioId || 'custom'),
        round_visibility: state.roundVisibility === 'simultaneous' ? 'simultaneous' : 'sequential',
        max_rounds: Number(state.scenarioParams?.max_rounds ?? 10),
        ...persistedSettings,
      },
    };

    try {
      await createExperimentTemplate(templatePayload);
      addNotification?.(
        'success',
        t('createExperiment.customBuilder.templateSavedSuccess', {
          defaultValue: 'Saved to your personal preset templates.',
        }),
      );
    } catch {
      addNotification?.(
        'warning',
        t('createExperiment.customBuilder.templateSavedFailed', {
          defaultValue: 'The simulation was created, but saving the personal preset template failed.',
        }),
      );
    }
  };

  return (
    <div className="studio-page">
      <ExperimentBuilder
        onCancel={() => navigate(sourceFlow === 'research-custom' ? '/simulations/create/custom' : '/simulations/create')}
        onBackFromStep2={() => navigate('/simulations/create/custom')}
        onComplete={handleLaunch}
      />
    </div>
  );
}

export default CreateExperimentPresetPage;
