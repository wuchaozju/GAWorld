/**
 * Step 2: Scenario Configuration
 *
 * Allows users to configure the selected scenario by editing its description
 * and setting dynamic parameters. Parameter fields are rendered based on the
 * scenario's parameter definitions using appropriate UI widgets.
 */

import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';
import { useExperimentBuilder } from '../../store/experiment-builder';
import ParameterField from './ParameterField';
import { ActionEditor } from './ActionEditor';
import GAWorldScenarioPanel from './GAWorldScenarioPanel';
import { buildGAWorldInitialParams } from './gaworldPresetModes';
import { ResourceConfig } from './ResourceConfig';

const DISTORTION_ONLY_PARAM_KEYS = new Set([
  'distortion_strength',
  'conflict_sensitivity',
  'block_probability',
]);

const isCascadeScenario = (parameterKeys: string[]) => parameterKeys.includes('cascade_mode');

// Payoff Input Component - 4 explicit inputs with dynamic action labels
interface PayoffInputProps {
  value: {
    cooperate_reward?: number;
    sucker_penalty?: number;
    temptation_reward?: number;
    defect_penalty?: number;
  };
  actionA?: string;  // label for first action (e.g., "Cooperate", "Stag", "Study")
  actionB?: string;  // label for second action (e.g., "Defect", "Hare", "Cheat")
  onChange: (value: {
    cooperate_reward: number;
    sucker_penalty: number;
    temptation_reward: number;
    defect_penalty: number;
  }) => void;
}

function PayoffInput({ value, actionA = 'Action 1', actionB = 'Action 2', onChange }: PayoffInputProps) {
  const { t } = useTranslation();
  const defaults = { cooperate_reward: 3, sucker_penalty: 0, temptation_reward: 5, defect_penalty: 1 };

  // Helper to translate action names
  const translateAction = (action: string) => {
    const normalized = action.toLowerCase().replace(/\s+/g, '_');
    const translated = t(`experimentBuilder.step2.actionNames.${normalized}`, { defaultValue: '' });
    return translated || action;
  };

  const translatedActionA = translateAction(actionA);
  const translatedActionB = translateAction(actionB);

  const update = (key: keyof typeof defaults, raw: string) => {
    onChange({
      cooperate_reward: value.cooperate_reward ?? defaults.cooperate_reward,
      sucker_penalty: value.sucker_penalty ?? defaults.sucker_penalty,
      temptation_reward: value.temptation_reward ?? defaults.temptation_reward,
      defect_penalty: value.defect_penalty ?? defaults.defect_penalty,
      [key]: parseInt(raw) || defaults[key],
    });
  };

  return (
    <div className="space-y-4">
      <div className="p-3 rounded-md text-sm mb-4" style={{ background: 'var(--ss-accent-warm-soft)', borderColor: 'var(--ss-layer-outline-strong)', border: '1px solid var(--ss-layer-outline-strong)' }}>
        <p className="font-medium mb-2" style={{ color: 'var(--ss-heading)' }}>{t('experimentBuilder.step2.payoffInput.yourPayoffs')}</p>
        <p className="text-xs" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step2.payoffInput.instruction')}</p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.step2.payoffInput.youThey', { actionA: translatedActionA, actionB: translatedActionA })}
          </label>
          <input
            type="number"
            value={value.cooperate_reward ?? defaults.cooperate_reward}
            onChange={(e) => update('cooperate_reward', e.target.value)}
            className="w-full px-3 py-2 border rounded-md"
            style={{ borderColor: 'var(--ss-border-strong)' }}
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.step2.payoffInput.youThey', { actionA: translatedActionA, actionB: translatedActionB })}
          </label>
          <input
            type="number"
            value={value.sucker_penalty ?? defaults.sucker_penalty}
            onChange={(e) => update('sucker_penalty', e.target.value)}
            className="w-full px-3 py-2 border rounded-md"
            style={{ borderColor: 'var(--ss-border-strong)' }}
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.step2.payoffInput.youThey', { actionA: translatedActionB, actionB: translatedActionA })}
          </label>
          <input
            type="number"
            value={value.temptation_reward ?? defaults.temptation_reward}
            onChange={(e) => update('temptation_reward', e.target.value)}
            className="w-full px-3 py-2 border rounded-md"
            style={{ borderColor: 'var(--ss-border-strong)' }}
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.step2.payoffInput.youThey', { actionA: translatedActionB, actionB: translatedActionB })}
          </label>
          <input
            type="number"
            value={value.defect_penalty ?? defaults.defect_penalty}
            onChange={(e) => update('defect_penalty', e.target.value)}
            className="w-full px-3 py-2 border rounded-md"
            style={{ borderColor: 'var(--ss-border-strong)' }}
          />
        </div>
      </div>
    </div>
  );
}

export const Step2StarterTemplate: React.FC = () => {
  const { t } = useTranslation();
  const {
    selectedScenarioData,
    scenarioDescription,
    scenarioParams,
    roundVisibility,
    turnOrder,
    setScenarioDescription,
    setScenarioParams,
    setRoundVisibility,
    setTurnOrder,
    loadDefaultAgentsForScenario,
  } = useExperimentBuilder();

  const [localRoundVisibility, setLocalRoundVisibility] = useState<'simultaneous' | 'sequential'>('simultaneous');
  const [localTurnOrder, setLocalTurnOrder] = useState<'fixed' | 'random'>('fixed');
  const isCustomScenario = selectedScenarioData?.id === 'custom';

  // Helper to get translated scenario name/description based on scenario ID and category
  const getScenarioName = () => {
    if (!selectedScenarioData) return '';
    const scenarioId = selectedScenarioData.id;
    const category = selectedScenarioData.category || 'game_theory';
    // Try to get translated name from locale files using the actual category
    const translatedName = t(`scenario.${category}.${scenarioId}.name`, { defaultValue: selectedScenarioData.name });
    return String(translatedName);
  };

  const getScenarioDescription = () => {
    if (!selectedScenarioData) return '';
    const scenarioId = selectedScenarioData.id;
    const category = selectedScenarioData.category || 'game_theory';
    // Try to get translated description from locale files using the actual category
    return String(t(`scenario.${category}.${scenarioId}.description`, { defaultValue: selectedScenarioData.description }));
  };

  // Update local state when store changes
  useEffect(() => {
    if (roundVisibility === 'simultaneous' || roundVisibility === 'sequential') {
      setLocalRoundVisibility(roundVisibility);
    }
    if (turnOrder) setLocalTurnOrder(turnOrder);
  }, [roundVisibility, turnOrder]);

  // Initialize scenario description from selected scenario (use translated version)
  useEffect(() => {
    if (selectedScenarioData && !scenarioDescription) {
      if (selectedScenarioData.id === 'custom') {
        return;
      }
      setScenarioDescription(getScenarioDescription());
    }
  }, [selectedScenarioData, scenarioDescription, setScenarioDescription]);

  // Initialize scenario params from defaults
  useEffect(() => {
    if (selectedScenarioData && selectedScenarioData.parameters && Object.keys(scenarioParams).length === 0) {
      const defaults = selectedScenarioData.id === 'gaworld'
        ? buildGAWorldInitialParams(selectedScenarioData.parameters)
        : selectedScenarioData.parameters.reduce<Record<string, unknown>>((accumulator, param) => {
          accumulator[param.key] = param.default;
          return accumulator;
        }, {});
      setScenarioParams(defaults);
    }
  }, [selectedScenarioData, scenarioParams, setScenarioParams]);

  const handleDescriptionChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setScenarioDescription(e.target.value);
    if (isCustomScenario) {
      setScenarioParams({ ...scenarioParams, custom_prompt: e.target.value });
    }
  };

  const handleParamChange = (key: string, value: string | number) => {
    setScenarioParams({ ...scenarioParams, [key]: value });
    if (selectedScenarioData?.id === 'gaworld' && key === 'agent_ids') {
      void loadDefaultAgentsForScenario('gaworld', String(value || '')).catch((error: unknown) => {
        console.error('Failed to refresh GAWorld default agents:', error);
      });
    }
  };

  const handlePayoffChange = (value: {
    cooperate_reward: number;
    sucker_penalty: number;
    temptation_reward: number;
    defect_penalty: number;
  }) => {
    setScenarioParams({
      ...scenarioParams,
      cooperate_reward: value.cooperate_reward,
      sucker_penalty: value.sucker_penalty,
      temptation_reward: value.temptation_reward,
      defect_penalty: value.defect_penalty,
    });
  };

  const getParamValue = (param: { key: string; default: unknown }) => {
    return scenarioParams[param.key] !== undefined
      ? scenarioParams[param.key]
      : param.default;
  };

  const getCustomTurnOrdering = () => {
    if (roundVisibility === 'random') {
      return 'random_sequential';
    }
    return roundVisibility === 'simultaneous' ? 'simultaneous' : 'sequential';
  };

  const handleCustomTurnOrderingChange = (value: string) => {
    setScenarioParams({ ...scenarioParams, turn_ordering: value });
    if (value === 'random_sequential') {
      setRoundVisibility('random');
      setTurnOrder('random');
      return;
    }
    if (value === 'simultaneous') {
      setRoundVisibility('simultaneous');
      setTurnOrder('fixed');
      return;
    }
    setRoundVisibility('sequential');
    setTurnOrder('fixed');
  };

  const getParamLabel = (param: { key: string; label: string }) => {
    return String(t(`experimentBuilder.paramLabels.${param.key}`, { defaultValue: param.label }));
  };

  const getParamDescription = (param: { key: string; description?: string }) => {
    return String(t(`experimentBuilder.paramDescriptions.${param.key}`, { defaultValue: param.description || '' }));
  };

  // Determine which editor to show based on scenario
  const getActionEditor = () => {
    const scenarioId = selectedScenarioData.id;

    if (scenarioId === 'battle_of_the_sexes' || scenarioId === 'stag_hunt') {
      // Translate default action names and descriptions
      const action1Name = selectedScenarioData.actions?.[0]?.name || 'Action 1';
      const action1Desc = selectedScenarioData.actions?.[0]?.description || '';
      const action2Name = selectedScenarioData.actions?.[1]?.name || 'Action 2';
      const action2Desc = selectedScenarioData.actions?.[1]?.description || '';

      return (
        <ActionEditor
          actions={[
            {
              id: 'action_1',
              nameParam: 'action_1_name',
              descParam: 'action_1_description',
              defaultName: t(`experimentBuilder.step2.actionNames.${action1Name}`, { defaultValue: action1Name }),
              defaultDesc: t(`experimentBuilder.step2.actionDescriptions.${action1Name}`, { defaultValue: action1Desc }),
            },
            {
              id: 'action_2',
              nameParam: 'action_2_name',
              descParam: 'action_2_description',
              defaultName: t(`experimentBuilder.step2.actionNames.${action2Name}`, { defaultValue: action2Name }),
              defaultDesc: t(`experimentBuilder.step2.actionDescriptions.${action2Name}`, { defaultValue: action2Desc }),
            },
          ]}
          values={scenarioParams as Record<string, string>}
          onChange={handleParamChange}
        />
      );
    }

    if (scenarioId === 'public_goods') {
      // Default values per design spec
      const defaultResourceName = t('experimentBuilder.resourceConfig.resourceOptions.tokens', { defaultValue: 'tokens' });

      return (
        <ResourceConfig
          values={{
            resource_name: (scenarioParams.resource_name as string) || defaultResourceName,
            tokens_per_round: (scenarioParams.tokens_per_round as number) ?? 10,
            multiplier: (scenarioParams.multiplier as number) ?? 1.3,
            deduction_budget_per_phase: (scenarioParams.deduction_budget_per_phase as number) ?? 0,
            deduction_cost_ratio: (scenarioParams.deduction_cost_ratio as number) ?? 3,
            deduction_anonymous: (scenarioParams.deduction_anonymous as boolean) ?? false,
            show_average_contribution: (scenarioParams.show_average_contribution as boolean) ?? false,
          }}
          onChange={handleParamChange}
        />
      );
    }

    return null;
  };

  if (!selectedScenarioData) {
    return (
      <div className="p-4 text-center" style={{ color: 'var(--ss-text-muted)' }}>
        {t('experimentBuilder.step2.selectScenarioFirst')}
      </div>
    );
  }

  if (isCustomScenario) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-xl font-semibold" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.step2.configureTitle', { name: getScenarioName() })}
          </h2>
          <p className="text-sm mt-1" style={{ color: 'var(--ss-text)' }}>
            {t('experimentBuilder.step2.configureSubtitle')}
          </p>
        </div>

        <div>
          <label
            htmlFor="custom-scenario-prompt"
            className="block text-sm font-medium mb-2"
            style={{ color: 'var(--ss-heading)' }}
          >
            {t('experimentBuilder.paramLabels.custom_prompt')}
          </label>
          <textarea
            id="custom-scenario-prompt"
            value={scenarioDescription}
            onChange={handleDescriptionChange}
            rows={8}
            className="w-full px-3 py-2 border rounded-lg shadow-sm focus:outline-none focus:ring-2 resize-y"
            style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
            placeholder="Describe the situation, roles, constraints, and what agents should discuss."
          />
        </div>

        <div>
          <label
            htmlFor="custom-turn-ordering"
            className="block text-sm font-medium mb-2"
            style={{ color: 'var(--ss-heading)' }}
          >
            Turn Ordering
          </label>
          <select
            id="custom-turn-ordering"
            value={String(scenarioParams.turn_ordering || getCustomTurnOrdering())}
            onChange={(e) => handleCustomTurnOrderingChange(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg"
            style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
          >
            <option value="sequential">sequential</option>
            <option value="random_sequential">random_sequential</option>
            <option value="simultaneous">simultaneous</option>
          </select>
        </div>
      </div>
    );
  }

  const hasParameters = selectedScenarioData.parameters.length > 0;
  const isGAWorldScenario = selectedScenarioData.id === 'gaworld';
  const cascadeMode = String(
    scenarioParams.cascade_mode
      ?? selectedScenarioData.parameters.find((param) => param.key === 'cascade_mode')?.default
      ?? 'strict_cascade'
  );
  const visibleParameters = selectedScenarioData.parameters.filter((param) => {
    // Exclude deduction category parameters - they're handled by ResourceConfig
    if (param.category === 'deduction') {
      return false;
    }
    // Exclude resource category parameters - they're handled by ResourceConfig
    if (param.category === 'resource') {
      return false;
    }
    if (!DISTORTION_ONLY_PARAM_KEYS.has(param.key)) {
      return true;
    }
    return cascadeMode === 'distortion_cascade';
  });
  const showCascadeModeCard = isCascadeScenario(selectedScenarioData.parameters.map((param) => param.key));
  const cascadeCardStyle = cascadeMode === 'distortion_cascade'
    ? { background: 'var(--ss-brand-soft)', borderColor: 'var(--ss-brand-primary)' }
    : { background: 'var(--ss-accent-warm-soft)', borderColor: 'var(--ss-layer-outline-strong)' };
  const cascadeBulletKeys = cascadeMode === 'distortion_cascade'
    ? ['point1', 'point2', 'point3']
    : ['point1', 'point2', 'point3'];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold" style={{ color: 'var(--ss-heading)' }}>
          {t('experimentBuilder.step2.configureTitle', { name: getScenarioName() })}
        </h2>
        <p className="text-sm mt-1" style={{ color: 'var(--ss-text)' }}>
          {t('experimentBuilder.step2.configureSubtitle')}
        </p>
      </div>

      {/* Scenario Description */}
      <div>
        <label
          htmlFor="scenario-description"
          className="block text-sm font-medium mb-2"
          style={{ color: 'var(--ss-heading)' }}
        >
          {t('experimentBuilder.step2.scenarioDescriptionLabel')}
        </label>
        <textarea
          id="scenario-description"
          value={scenarioDescription}
          onChange={handleDescriptionChange}
          rows={4}
          className="w-full px-3 py-2 border rounded-lg shadow-sm focus:outline-none focus:ring-2 resize-y"
          style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
          placeholder={t('experimentBuilder.step2.scenarioDescriptionPlaceholder')}
        />
      </div>

      {showCascadeModeCard && (
        <div className={`rounded-lg border p-4`} style={cascadeCardStyle}>
          <div className="flex items-center justify-between gap-3 mb-2">
            <div>
              <h3 className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                {t(`experimentBuilder.step2.cascadeCards.${cascadeMode}.title`)}
              </h3>
              <p className="text-sm mt-1" style={{ color: 'var(--ss-heading)' }}>
                {t(`experimentBuilder.step2.cascadeCards.${cascadeMode}.summary`)}
              </p>
            </div>
            <span
              className="rounded-full border px-3 py-1 text-xs font-medium"
              style={{ background: 'var(--ss-page-surface)', color: 'var(--ss-heading)', borderColor: 'var(--ss-border)' }}
            >
              {t(`experimentBuilder.step2.cascadeCards.${cascadeMode}.badge`)}
            </span>
          </div>
          <ul className="mt-3 space-y-2 text-sm" style={{ color: 'var(--ss-heading)' }}>
            {cascadeBulletKeys.map((key) => (
              <li key={key} className="flex items-start gap-2">
                <span className="mt-0.5" style={{ color: 'var(--ss-text-muted)' }}>•</span>
                <span>{t(`experimentBuilder.step2.cascadeCards.${cascadeMode}.${key}`)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Dynamic Parameter Fields or Payoff Input */}
      {/* Action Editor for configurable scenarios */}
      {getActionEditor()}
      {selectedScenarioData.display_type === 'payoff_matrix' ? (
        <PayoffInput
          value={scenarioParams as { cooperate_reward?: number; defect_penalty?: number }}
          actionA={String(scenarioParams.action_1_name || selectedScenarioData.actions?.[0]?.name || 'Action 1')}
          actionB={String(scenarioParams.action_2_name || selectedScenarioData.actions?.[1]?.name || 'Action 2')}
          onChange={handlePayoffChange}
        />
      ) : isGAWorldScenario ? (
        <GAWorldScenarioPanel
          scenarioParams={scenarioParams}
          setScenarioParams={setScenarioParams}
        />
      ) : hasParameters ? (
        <div className="space-y-4">
          <h3 className="text-sm font-medium" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.step2.parametersTitle')}
          </h3>
          {visibleParameters.map((param) => {
            const value = getParamValue(param);
            const description = getParamDescription(param);

            return (
              <div key={param.key} className="space-y-1">
                <label className="block text-sm font-medium" style={{ color: 'var(--ss-heading)' }}>
                  {getParamLabel(param)}
                </label>
                {description && (
                  <p className="text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
                    {description}
                  </p>
                )}
                <ParameterField
                  param={{
                    type: param.type === 'number' ? 'integer' : 'string',
                    default: param.default,
                    ui_hint: param.ui_hint || 'text',
                    min: param.min,
                    max: param.max,
                    step: param.step,
                    options: param.options,
                    placeholder: param.placeholder,
                  }}
                  value={value}
                  onChange={(val) => handleParamChange(param.key, val)}
                />
              </div>
            );
          })}
        </div>
      ) : (
        <div className="p-3 rounded-lg border" style={{ background: 'var(--ss-page-surface-muted)', borderColor: 'var(--ss-border)' }}>
          <p className="text-sm" style={{ color: 'var(--ss-text)' }}>
            {t('experimentBuilder.step2.noParameters')}
          </p>
        </div>
      )}

      {/* Round Settings */}
      {hasParameters && (
        <div className="border-t pt-4 mt-4">
          <h3 className="font-medium mb-3" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.roundSettings.title')}
          </h3>

          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-heading)' }}>
                {t('experimentBuilder.roundSettings.roundVisibility.label')}
              </label>
              <select
                value={localRoundVisibility}
                onChange={(e) => {
                  const val = e.target.value as 'simultaneous' | 'sequential';
                  setLocalRoundVisibility(val);
                  setRoundVisibility(val);
                }}
                className="w-full px-3 py-2 border rounded-lg"
                style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
              >
                <option value="simultaneous">
                  {t('experimentBuilder.roundSettings.roundVisibility.simultaneous')}
                </option>
                <option value="sequential">
                  {t('experimentBuilder.roundSettings.roundVisibility.sequential')}
                </option>
              </select>
            </div>

            {localRoundVisibility === 'sequential' && (
              <div>
                <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-heading)' }}>
                  {t('experimentBuilder.roundSettings.turnOrder.label')}
                </label>
                <select
                  value={localTurnOrder}
                  onChange={(e) => {
                    const val = e.target.value as 'fixed' | 'random';
                    setLocalTurnOrder(val);
                    setTurnOrder(val);
                  }}
                  className="w-full px-3 py-2 border rounded-lg"
                  style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
                >
                  <option value="fixed">
                    {t('experimentBuilder.roundSettings.turnOrder.fixed')}
                  </option>
                  <option value="random">
                    {t('experimentBuilder.roundSettings.turnOrder.random')}
                  </option>
                </select>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
