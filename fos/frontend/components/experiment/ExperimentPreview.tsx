/**
 * Experiment Preview Component
 *
 * Displays a human-readable summary of the experiment configuration
 * before creation, shown on Step 5.
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { useExperimentBuilder } from '../../store/experiment-builder';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';

const INTERACTION_LABELS: Record<string, string> = {
  strategic_decisions: 'Strategic Decisions',
  opinions_influence: 'Opinions & Influence',
  network_spread: 'Network & Spread',
  markets_exchange: 'Markets & Exchange',
  spatial_movement: 'Spatial & Movement',
  open_conversation: 'Open Conversation',
};

const NETWORK_LABELS: Record<string, string> = {
  complete: 'Everyone talks to everyone',
  sbm: 'Small clusters (SBM)',
  barabasi: 'Scale-free (hub-and-spoke)',
  custom: 'Custom network',
};

const SUCCESS_LABELS: Record<string, string> = {
  fixed_rounds: 'Fixed number of rounds',
  convergence: 'Convergence (agreement within tolerance)',
  unanimity: 'Unanimity (all agents choose the same)',
  no_conflicts: 'No conflicts',
};

const TURN_ORDER_LABELS: Record<string, string> = {
  simultaneous: 'Simultaneous (all agents act at once)',
  sequential: 'Sequential (agents take turns)',
  random: 'Random (different order each round)',
};

const UPDATE_LABELS: Record<string, string> = {
  none: 'None (no changes between rounds)',
  imitate: 'Imitation (copy successful strategies)',
  average: 'Averaging (opinions shift toward average)',
  reinforce: 'Reinforcement (successful behaviors reinforced)',
};

export const ExperimentPreview: React.FC = () => {
  const { t } = useTranslation();
  const {
    selectedScenarioData,
    scenarioDescription,
    agentTypes,
    networkType,
    turnOrder,
    interRoundUpdate,
    metrics,
    availableActions,
    selectedActionIds,
  } = useExperimentBuilder();

  const interactionTypes = selectedScenarioData ? [selectedScenarioData.category] : [];
  const scenario = scenarioDescription || selectedScenarioData?.description || '';
  const mechanicConfigs: Record<string, any> = {};
  const successCondition = { type: 'fixed_rounds', maxRounds: undefined as number | undefined };
  const selectedMetrics = metrics || [];
  const selectedActions = availableActions.filter((action) => selectedActionIds.includes(action.name));

  const totalAgents = agentTypes.reduce((sum, t) => sum + t.count, 0);

  const hasStrategic = interactionTypes.includes('strategic_decisions');
  const hasOpinion = interactionTypes.includes('opinions_influence');
  const hasNetwork = interactionTypes.includes('network_spread');

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>{t('components.experimentDesignModal.previewTitle')}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          {/* Interaction Types */}
          <div>
            <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--ss-text)' }}>
              Interaction Patterns
            </h4>
            <div className="flex flex-wrap gap-2">
              {interactionTypes.map((type) => (
                <span
                  key={type}
                  className="px-3 py-1 rounded-full text-sm"
                  style={{ background: 'var(--ss-accent-warm-soft)', color: 'var(--ss-text)' }}
                >
                  {INTERACTION_LABELS[type] || type}
                </span>
              ))}
            </div>
          </div>

          {/* Scenario */}
          {scenario && (
            <div>
              <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--ss-text)' }}>
                Scenario
              </h4>
              <p className="text-sm p-3 rounded border" style={{ background: 'var(--ss-page-surface-muted)', borderColor: 'var(--ss-border)', color: 'var(--ss-text-muted)' }}>
                {scenario}
              </p>
            </div>
          )}

          {/* Agents */}
          <div>
            <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--ss-text)' }}>
              Agents ({totalAgents} total)
            </h4>
            <div className="space-y-2">
              {agentTypes.map((type) => (
                <div
                  key={type.id}
                  className="flex items-center justify-between text-sm p-2 rounded"
                  style={{ background: 'var(--ss-page-surface-muted)' }}
                >
                  <span className="font-medium" style={{ color: 'var(--ss-heading)' }}>
                    {type.label}
                  </span>
                  <span style={{ color: 'var(--ss-text-muted)' }}>
                    {type.count} agent{type.count !== 1 ? 's' : ''}
                  </span>
                </div>
              ))}
              {agentTypes.length === 0 && (
                <p className="text-sm italic" style={{ color: 'var(--ss-text-subtle)' }}>
                  No agents defined
                </p>
              )}
            </div>
          </div>

          {/* Mechanic Configs */}
          {hasStrategic && mechanicConfigs.strategic_choice && (
            <div>
              <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--ss-text)' }}>
                Strategic Choices
              </h4>
              <div className="text-sm space-y-1" style={{ color: 'var(--ss-text-muted)' }}>
                <p>Options: {mechanicConfigs.strategic_choice.strategies?.join(', ') || 'Not defined'}</p>
                <p>Payoff Mode: {mechanicConfigs.strategic_choice.payoffMode || 'pairwise'}</p>
                <p>Visibility: {mechanicConfigs.strategic_choice.payoffVisibility || 'private'}</p>
              </div>
            </div>
          )}

          {hasOpinion && mechanicConfigs.opinion && (
            <div>
              <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--ss-text)' }}>
                Opinions & Influence
              </h4>
              <div className="text-sm space-y-1" style={{ color: 'var(--ss-text-muted)' }}>
                <p>Dimension: {mechanicConfigs.opinion.opinionDimensions?.[0]?.name || 'Not defined'}</p>
                <p>Influence: {mechanicConfigs.opinion.influenceModel || 'bounded_confidence'}</p>
                {mechanicConfigs.opinion.influenceModel === 'bounded_confidence' && (
                  <p>Open-mindedness: {mechanicConfigs.opinion.confidenceThreshold || 30}</p>
                )}
              </div>
            </div>
          )}

          {hasNetwork && mechanicConfigs.network_dynamics && (
            <div>
              <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--ss-text)' }}>
                Network Dynamics
              </h4>
              <div className="text-sm space-y-1" style={{ color: 'var(--ss-text-muted)' }}>
                <p>Spreads: {mechanicConfigs.network_dynamics.propagationType || 'opinion'}</p>
                <p>Evolution: {mechanicConfigs.network_dynamics.evolutionModel || 'none'}</p>
              </div>
            </div>
          )}

          {/* Structure Settings */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--ss-text)' }}>
                Network Structure
              </h4>
              <p className="text-sm" style={{ color: 'var(--ss-text-muted)' }}>
                {NETWORK_LABELS[networkType] || networkType}
              </p>
            </div>

            <div>
              <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--ss-text)' }}>
                Stopping Condition
              </h4>
              <p className="text-sm" style={{ color: 'var(--ss-text-muted)' }}>
                {SUCCESS_LABELS[successCondition.type] || successCondition.type}
              </p>
              {successCondition.maxRounds && (
                <p className="text-xs" style={{ color: 'var(--ss-text-subtle)' }}>
                  Max {successCondition.maxRounds} rounds
                </p>
              )}
            </div>

            <div>
              <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--ss-text)' }}>
                Turn Order
              </h4>
              <p className="text-sm" style={{ color: 'var(--ss-text-muted)' }}>
                {TURN_ORDER_LABELS[turnOrder] || turnOrder}
              </p>
            </div>

            <div>
              <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--ss-text)' }}>
                Inter-Round Update
              </h4>
              <p className="text-sm" style={{ color: 'var(--ss-text-muted)' }}>
                {UPDATE_LABELS[interRoundUpdate.type] || interRoundUpdate.type}
              </p>
            </div>
          </div>

          {selectedActions.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                Available Actions
              </h4>
              <div className="flex flex-wrap gap-2">
                {selectedActions.map((action) => (
                  <span
                    key={action.name}
                    className="px-2 py-1 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded text-sm"
                  >
                    {action.name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Metrics */}
          {selectedMetrics.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--ss-text)' }}>
                Metrics to Collect
              </h4>
              <div className="flex flex-wrap gap-2">
                {selectedMetrics.map((metric) => (
                  <span
                    key={metric}
                    className="px-2 py-1 rounded text-sm"
                    style={{ background: 'var(--ss-surface-strong)', color: 'var(--ss-text)' }}
                  >
                    {metric}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
};

export default ExperimentPreview;
