/**
 * Step 3: Action Selector
 *
 * Displays available actions as toggle cards.
 * Shows all category actions when scenario has category_actions.
 * Users can enable/disable actions for the selected scenario.
 * At least one action must be selected.
 */

import React, { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useExperimentBuilder } from '../../store/experiment-builder';
import { Circle, X } from 'lucide-react';
import { ActionDef } from '../../services/scenarios';
import { isPolicyCascadeScenario } from '../../utils/policyCascade';

const POLICY_SCENE_ACTION_IDS = [
  'send_message',
  'yield',
  'report_upward',
  'escalate_complaint',
  'consult_peer',
  'notify_subordinate',
  'announce_policy_adjustment',
];

const isPolicyCascadeScenarioData = (scenario: {
  id?: string;
  name?: string;
  sceneType?: string;
  parameters?: Array<{ key: string }>;
} | null | undefined): boolean => {
  return isPolicyCascadeScenario(scenario);
};

interface ActionToggleCardProps {
  name: string;
  description: string;
  selected: boolean;
  onToggle: () => void;
  isCustom?: boolean;
  onRemove?: () => void;
  removeLabel?: string;
}

const ActionToggleCard: React.FC<ActionToggleCardProps> = ({
  name,
  description,
  selected,
  onToggle,
  isCustom = false,
  onRemove,
  removeLabel,
}) => {
  return (
    <div
      className="p-4 border-2 rounded-lg transition-all"
      style={selected
        ? { background: 'var(--ss-accent-warm-soft)', borderColor: 'var(--ss-brand-primary)' }
        : { background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }
      }
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <Circle
            className={`w-5 h-5 flex-shrink-0 mt-0.5 ${selected ? 'fill-current' : ''}`}
            style={{ color: selected ? 'var(--ss-brand-primary)' : 'var(--ss-text-subtle)' }}
          />
          <div className="flex-1 min-w-0">
            <h4 className="font-semibold text-sm" style={{ color: 'var(--ss-heading)' }}>
              {name}
            </h4>
            <p className="text-sm mt-1 line-clamp-2" style={{ color: 'var(--ss-text)' }}>
              {description}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {isCustom && onRemove && (
            <button
              onClick={onRemove}
              className="p-1.5 rounded transition-colors"
              style={{ color: 'var(--ss-text-subtle)' }}
              type="button"
              aria-label={removeLabel}
            >
              <X size={16} />
            </button>
          )}
          <button
            onClick={onToggle}
            className="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
            style={{ background: selected ? 'var(--ss-brand-primary)' : 'var(--ss-border-strong)' }}
            type="button"
            aria-pressed={selected}
          >
            <span
              className={`
                inline-block h-4 w-4 transform rounded-full transition-transform
                ${selected ? 'translate-x-6' : 'translate-x-1'}
              `}
              style={{ background: 'var(--ss-page-surface)' }}
            />
          </button>
        </div>
      </div>
    </div>
  );
};

export const Step3Scenario: React.FC = () => {
  const { t } = useTranslation();
  const {
    selectedScenarioData,
    scenarioParams,
    availableActions,
    selectedActionIds,
    setAvailableActions,
    setSelectedActionIds,
    toggleActionId,
    validationErrors,
  } = useExperimentBuilder();

  const buildPolicySceneActions = (): ActionDef[] => [
    {
      name: 'send_message',
      description: t('experimentBuilder.step3.policyActions.send_message.description'),
    },
    {
      name: 'yield',
      description: t('experimentBuilder.step3.policyActions.yield.description'),
    },
    {
      name: 'report_upward',
      description: t('experimentBuilder.step3.policyActions.report_upward.description'),
    },
    {
      name: 'escalate_complaint',
      description: t('experimentBuilder.step3.policyActions.escalate_complaint.description'),
    },
    {
      name: 'consult_peer',
      description: t('experimentBuilder.step3.policyActions.consult_peer.description'),
    },
    {
      name: 'notify_subordinate',
      description: t('experimentBuilder.step3.policyActions.notify_subordinate.description'),
    },
    {
      name: 'announce_policy_adjustment',
      description: t('experimentBuilder.step3.policyActions.announce_policy_adjustment.description'),
    },
  ];

  const getPolicyActionLabel = (actionName: string): string => {
    return t(`experimentBuilder.step3.policyActions.${actionName}.label`, { defaultValue: actionName });
  };

  const getActionName = (actionName: string): string => {
    const normalized = actionName.toLowerCase().replace(/\s+/g, '_');
    const translated = t(`experimentBuilder.payoffMatrix.actionNames.${normalized}`, { defaultValue: '' });
    return translated || actionName;
  };

  const getActionDescription = (actionName: string, fallback: string): string => {
    const normalized = actionName.toLowerCase().replace(/\s+/g, '_');
    const translated = t(`experimentBuilder.payoffMatrix.actions.${normalized}`, { defaultValue: '' });
    return translated || fallback;
  };

  // Check if actions are dynamically generated
  const generatorParam = selectedScenarioData?.parameters?.find(
    (p) => p.generates_actions === true
  );

  /**
   * Generate actions from a choices parameter value.
   * Parses comma-separated choices and creates action definitions.
   */
  const generateActionsFromChoices = (choicesValue: string): ActionDef[] => {
    const choices = choicesValue
      .split(',')
      .map((c) => c.trim())
      .filter(Boolean);

    return choices.map((choice) => ({
      name: choice,
      description: t('experimentBuilder.actions.chooseAction', { action: choice }),
    }));
  };

  // Initialize available actions from scenario data
  // Use category_actions if available, otherwise fall back to scenario.actions
  // If a parameter has generates_actions=true, generate actions from that parameter
  useEffect(() => {
    if (selectedScenarioData) {
      // Check if any parameter generates actions
      const generatorParam = selectedScenarioData.parameters?.find(
        (p) => p.generates_actions === true
      );

      if (generatorParam) {
        // Get the current value of the generating parameter
        const paramValue =
          (scenarioParams[generatorParam.key] as string) ||
          (generatorParam.default as string) ||
          '';

        // Generate actions from the parameter value
        const generatedActions = generateActionsFromChoices(paramValue);
        setAvailableActions(generatedActions);

        // Preserve existing selections for actions that still exist
        const existingSelectedIds = selectedActionIds.filter((id) =>
          generatedActions.some((a) => a.name === id)
        );
        // Find new actions that weren't in the previous list
        const newActionIds = generatedActions
          .filter((a) => !availableActions.some((prev) => prev.name === a.name))
          .map((a) => a.name);

        if (existingSelectedIds.length === 0 && newActionIds.length > 0) {
          // First time or no existing selections - select all
          setSelectedActionIds(generatedActions.map((a) => a.name));
        } else {
          // Preserve existing + add new
          setSelectedActionIds([...existingSelectedIds, ...newActionIds]);
        }
      } else {
        // Use category_actions if available, otherwise use scenario.actions
        const isPolicyCascadeScenario = isPolicyCascadeScenarioData(selectedScenarioData);
        const rawActions =
          selectedScenarioData.category_actions || selectedScenarioData.actions || [];
        const actionsToShow = isPolicyCascadeScenario
          ? buildPolicySceneActions()
          : rawActions;
        setAvailableActions(actionsToShow);

        // Use default_action_ids if available, otherwise select all actions by default
        const preferredIds = isPolicyCascadeScenario
          ? POLICY_SCENE_ACTION_IDS
          : (selectedScenarioData.default_action_ids || actionsToShow.map((a) => a.name));
        const defaultIds = preferredIds
          .map((id) => actionsToShow.find((action) => action.name === id || action.id === id)?.name)
          .filter((id): id is string => Boolean(id));
        setSelectedActionIds(defaultIds);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedScenarioData, scenarioParams, setAvailableActions, setSelectedActionIds]);

  const isPolicyCascadeScenario = isPolicyCascadeScenarioData(selectedScenarioData);

  // Combine preset and custom actions
  const presetActionNames = new Set(
    (selectedScenarioData?.category_actions || selectedScenarioData?.actions || []).map((action) => action.name)
  );

  const allActions = availableActions.map((action) => ({
    ...action,
    isCustom: !presetActionNames.has(action.name),
  }));

  const handleToggleAction = (actionName: string) => {
    // Prevent deselecting if it's the last action
    const isCurrentlySelected = selectedActionIds.includes(actionName);
    const willBeEmpty = isCurrentlySelected && selectedActionIds.length === 1;

    if (willBeEmpty) {
      // Don't allow deselecting the last action
      return;
    }

    toggleActionId(actionName);
  };

  const handleRemoveCustomAction = (actionName: string) => {
    setAvailableActions(availableActions.filter((a) => a.name !== actionName));
    setSelectedActionIds(selectedActionIds.filter((id) => id !== actionName));
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold" style={{ color: 'var(--ss-heading)' }}>
          {t('experimentBuilder.step3.title')}
        </h2>
        <p className="text-sm mt-1" style={{ color: 'var(--ss-text)' }}>
          {t('experimentBuilder.step3.subtitle')}
        </p>
        <div className="mt-3 rounded-lg border px-4 py-3 text-sm" style={{ background: 'var(--ss-accent-warm-soft)', borderColor: 'var(--ss-layer-outline-strong)', color: 'var(--ss-text)' }}>
          <div className="font-medium">{t('experimentBuilder.step3.linkedTitle')}</div>
          <div className="mt-1">{t('experimentBuilder.step3.linkedDesc')}</div>
        </div>
        {selectedScenarioData?.category_actions && (
          <p className="text-xs mt-2" style={{ color: 'var(--ss-text)' }}>
            {t('experimentBuilder.step3.categoryInfo', { category: selectedScenarioData.category })}
          </p>
        )}
      </div>

      {/* Dynamic actions info */}
      {generatorParam && (
        <div className="p-3 border rounded-lg" style={{ background: 'var(--ss-accent-warm-soft)', borderColor: 'var(--ss-layer-outline-strong)' }}>
          <p className="text-sm" style={{ color: 'var(--ss-text)' }}>
            <strong>{t('experimentBuilder.dynamicActionsInfo.title')}</strong>{' '}
            {t('experimentBuilder.dynamicActionsInfo.message', { paramLabel: generatorParam.label })}
          </p>
        </div>
      )}

      {/* Validation Error */}
      {validationErrors.actions && (
        <div className="p-3 border rounded-lg" style={{ background: 'var(--ss-danger-soft)', borderColor: 'var(--ss-danger)' }}>
          <p className="text-sm" style={{ color: 'var(--ss-danger)' }}>{validationErrors.actions}</p>
        </div>
      )}

      {/* Action Toggle Cards */}
      <div className="space-y-3">
        {allActions.length === 0 ? (
          <div className="p-8 text-center border border-dashed rounded-lg" style={{ borderColor: 'var(--ss-border-strong)' }}>
            <p className="text-sm" style={{ color: 'var(--ss-text)' }}>
              {t('experimentBuilder.step3.noActions')}
            </p>
          </div>
        ) : (
          allActions.map((action) => (
            <ActionToggleCard
              key={action.name}
              name={isPolicyCascadeScenario ? getPolicyActionLabel(action.name) : getActionName(action.name)}
              description={isPolicyCascadeScenario ? action.description : getActionDescription(action.name, action.description)}
              selected={selectedActionIds.includes(action.name)}
              onToggle={() => handleToggleAction(action.name)}
              isCustom={action.isCustom}
              onRemove={action.isCustom ? () => handleRemoveCustomAction(action.name) : undefined}
              removeLabel={t('experimentBuilder.step3.removeAction')}
            />
          ))
        )}
      </div>

      {/* Selected Count */}
      {allActions.length > 0 && (
        <div className="text-sm" style={{ color: 'var(--ss-text)' }}>
          {t('experimentBuilder.step3.actionsSelected', { selected: selectedActionIds.length, total: allActions.length })}
        </div>
      )}
    </div>
  );
};
