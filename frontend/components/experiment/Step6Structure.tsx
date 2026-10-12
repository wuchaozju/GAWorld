/**
 * Step 6: Prompt Preview
 *
 * Displays a preview of exactly what each agent type will see
 * at the start of the simulation. This matches the backend's
 * prompt_builder.py build_prompt() function template.
 *
 * Uses a split-panel layout with a virtualized agent type list
 * on the left and a scrollable preview panel on the right,
 * preventing layout issues with large numbers of agents.
 *
 * Exports: Step6Structure
 */

import React, { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useExperimentBuilder } from '../../store/experiment-builder';
import { AlertCircle, ChevronRight, User } from 'lucide-react';

interface PromptPreviewPanelProps {
  agentTypeLabel: string;
  agentTypeProfile: string;
  agentTypeRolePrompt: string;
  agentTypeProperties: Record<string, unknown>;
  scenarioId: string;
  scenarioDescription: string;
  scenarioParams: Record<string, unknown>;
  availableActions: Array<{ name: string; description: string }>;
  selectedActionIds: string[];
  totalAgents: number;
  roundVisibility: string;
  socialNetwork: Record<string, unknown>;
}

/**
 * Component that renders the prompt preview for a single agent type.
 * Matches the 5-section prompt structure from backend's prompt_builder.py:
 * 1. Agent Description
 * 2. Scenario (with parameters intertwined for PGG)
 * 3. Available Actions (phase-filtered for PGG)
 * 4. Context (first round - no previous context)
 * 5. Output Format (JSON response instruction)
 */
const PromptPreviewPanel: React.FC<PromptPreviewPanelProps> = ({
  agentTypeLabel,
  agentTypeProfile,
  agentTypeRolePrompt,
  agentTypeProperties,
  scenarioId,
  scenarioDescription,
  scenarioParams,
  availableActions,
  selectedActionIds,
  totalAgents,
  roundVisibility,
  socialNetwork,
}) => {
  const { t } = useTranslation();

  // Filter actions to only selected ones
  const selectedActions = availableActions.filter((a) =>
    selectedActionIds.includes(a.name)
  );

  // For PUBLIC_GOODS: filter to only contribute phase actions for first round
  const contributePhaseActions = selectedActions.filter((a) =>
    ['Allocate', 'Keep'].includes(a.name)
  );

  // For PUBLIC_GOODS: use contribute phase actions, otherwise use all selected
  const displayActions = scenarioId === 'public_goods' ? contributePhaseActions : selectedActions;

  // Build actions list string
  const actionsList = displayActions
    .map((a) => `- ${a.name}: ${a.description}`)
    .join('\n  ');

  // Build the actions string for the response format
  const actionsForResponse = displayActions.map((a) => `"${a.name}"`).join(' or ');

  // Format parameter key for display (snake_case to Title Case)
  const formatParamKey = (key: string): string => {
    return key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
  };

  const formatParamValue = (value: unknown): string => {
    if (Array.isArray(value)) {
      return value.map((item) => (typeof item === 'string' ? item : JSON.stringify(item))).join(', ');
    }
    if (value && typeof value === 'object') {
      return JSON.stringify(value);
    }
    return String(value);
  };

  // Build formatted scenario description for PUBLIC_GOODS
  const getFormattedScenario = () => {
    if (scenarioId === 'public_goods') {
      const tokensPerRound = Number(scenarioParams.tokens_per_round ?? 10);
      const resourceName = String(scenarioParams.resource_name ?? 'tokens');
      const multiplier = Number(scenarioParams.multiplier ?? 1.3);
      const numMembers = totalAgents || 4;
      const deductionBudget = Number(scenarioParams.deduction_budget_per_phase ?? 0);
      const deductionCostRatio = Number(scenarioParams.deduction_cost_ratio ?? 3);
      const deductionAnonymous = Boolean(scenarioParams.deduction_anonymous ?? false);

      const rawDescription = scenarioDescription ||
        'Each person has resources and decides how much to contribute to a shared pool. The pool is multiplied and distributed equally among all members, regardless of contribution.';
      const baseDescription = rawDescription.replace(/\bagent(s)?\b/gi, (match) =>
        match.toLowerCase() === 'agents' ? 'members' : 'person'
      );

      let formattedScenario = `In this experiment, you receive ${tokensPerRound} ${resourceName} each round. ${baseDescription}\n\nThe total group contribution is multiplied by ${multiplier} and distributed equally among all ${numMembers} members. You keep any ${resourceName} you do not allocate.`;

      if (deductionBudget > 0) {
        const anonymityText = deductionAnonymous
          ? 'Your reductions are anonymous - targets will not know who reduced their resources.'
          : 'Your reductions are visible - targets will see who reduced their resources.';
        formattedScenario += `\n\nAfter the contribution phase, you have the opportunity to reduce other members' ${resourceName}. You have a deduction budget of ${deductionBudget} points. For each 1 point from your budget, the target loses ${deductionCostRatio} ${resourceName}. ${anonymityText}`;
      }

      return formattedScenario;
    }
    return scenarioDescription;
  };

  // Determine which parameters to show
  const getDisplayParams = () => {
    if (scenarioId === 'custom') {
      const hiddenKeys = new Set([
        'custom_prompt',
        'turn_ordering',
        'ai_scientist_evidence',
        'ai_scientist_source_sections',
        'ai_scientist_action_overrides',
        'ai_scientist_source_excerpt',
      ]);
      return Object.entries(scenarioParams).filter(([key]) => !hiddenKeys.has(key));
    }
    if (scenarioId === 'public_goods') {
      const excludedKeys = [
        'resource_name',
        'tokens_per_round',
        'multiplier',
        'initial_amount',
        'deduction_budget_per_phase',
        'deduction_cost_ratio',
        'deduction_anonymous',
      ];
      return Object.entries(scenarioParams).filter(([key]) => !excludedKeys.includes(key));
    }
    return Object.entries(scenarioParams);
  };

  const displayParams = getDisplayParams();
  const formattedScenario = getFormattedScenario();
  const customTurnOrdering =
    roundVisibility === 'random'
      ? 'random_sequential'
      : roundVisibility === 'simultaneous'
        ? 'simultaneous'
        : 'sequential';
  const networkEdges = Array.isArray((socialNetwork as { edges?: unknown }).edges)
    ? ((socialNetwork as { edges: unknown[] }).edges.length)
    : 0;

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{
        border: `1px solid var(--ss-border-strong)`,
        background: 'var(--ss-page-surface-muted)',
      }}
    >
      {/* Header */}
      <div
        className="px-4 py-2 border-b"
        style={{
          background: 'var(--ss-surface-strong)',
          borderColor: 'var(--ss-border-strong)',
        }}
      >
        <span className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
          {t('experimentBuilder.promptPreview.agentTypeLabel', { name: agentTypeLabel })}
        </span>
      </div>

      {/* Prompt Content */}
      <div
        className="p-4 font-mono text-sm whitespace-pre-wrap"
        style={{
          background: 'var(--ss-page-surface)',
          color: 'var(--ss-text)',
        }}
      >
        {/* Section 1: Agent Description */}
        <div className="mb-4">
          <span style={{ color: 'var(--ss-brand-primary)' }}>{t('experimentBuilder.promptPreview.youAre')}</span> {agentTypeLabel}.
          {agentTypeRolePrompt ? (
            <>
              {' '}
              {agentTypeRolePrompt}
            </>
          ) : agentTypeProfile ? (
            <>
              {' '}
              {agentTypeProfile}
            </>
          ) : null}
        </div>

        {/* Section 2: Scenario */}
        <div className="mb-4">
          <div className="font-semibold mb-1" style={{ color: 'var(--ss-heading)' }}>{t('experimentBuilder.step6.scenario')}</div>
          {formattedScenario || (
            <span className="italic" style={{ color: 'var(--ss-text-subtle)' }}>{t('experimentBuilder.step6.noScenarioDescription')}</span>
          )}
        </div>

        {/* Section 2b: Additional Parameters */}
        {displayParams.length > 0 && (
          <div className="mb-4">
            <div className="font-semibold mb-1" style={{ color: 'var(--ss-heading)' }}>{t('experimentBuilder.step6.additionalParameters')}</div>
            <div className="pl-2">
              {displayParams.map(([key, value]) => (
                <div key={key}>- {formatParamKey(key)}: {formatParamValue(value)}</div>
              ))}
            </div>
          </div>
        )}

        {scenarioId === 'custom' && (
          <div className="mb-4">
            <div className="font-semibold mb-1" style={{ color: 'var(--ss-heading)' }}>{t('experimentBuilder.step6.turnOrdering')}</div>
            <div className="pl-2">{customTurnOrdering}</div>
            <div className="font-semibold mt-3 mb-1" style={{ color: 'var(--ss-heading)' }}>{t('experimentBuilder.step6.network')}</div>
            <div className="pl-2">{networkEdges} connection{networkEdges === 1 ? '' : 's'}</div>
          </div>
        )}

        {/* Section 3: Available Actions */}
        <div className="mb-4">
          <div className="font-semibold mb-1" style={{ color: 'var(--ss-heading)' }}>{t('experimentBuilder.step6.availableActions')}</div>
          {displayActions.length > 0 ? (
            <div className="pl-2">{actionsList}</div>
          ) : (
            <span className="italic" style={{ color: 'var(--ss-text-subtle)' }}>{t('experimentBuilder.step6.noActionsSelected')}</span>
          )}
        </div>

        {/* Section 4: Context */}
        <div className="mb-4">
          <div className="font-semibold mb-1" style={{ color: 'var(--ss-heading)' }}>{t('experimentBuilder.step6.context')}</div>
          <div className="pl-2">{t('experimentBuilder.step6.firstRound')}</div>
        </div>

        {/* Section 5: Output Format */}
        <div
          className="pt-3 mt-3"
          style={{ borderTop: '1px solid var(--ss-border)' }}
        >
          <div className="font-semibold mb-1" style={{ color: 'var(--ss-heading)' }}>{t('experimentBuilder.step6.yourResponse')}</div>
          {displayActions.length > 0 ? (
            scenarioId === 'custom' ? (
              <div className="pl-2">
                {displayActions.map((action) => (
                  <div key={action.name}>{`{"action": "${action.name}", "message": ${action.name.toLowerCase().includes('speak') ? '"..."' : 'null'}}`}</div>
                ))}
              </div>
            ) : (
              <div className="pl-2">
                Respond with only JSON: {`{{"action": <${actionsForResponse}>}}`}
              </div>
            )
          ) : (
            <div className="pl-2 italic" style={{ color: 'var(--ss-text-subtle)' }}>
              Add actions in Step 3 to see the response format
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export const Step6Structure: React.FC = () => {
  const { t } = useTranslation();
  const {
    agentTypes,
    selectedScenarioId,
    scenarioDescription,
    scenarioParams,
    availableActions,
    selectedActionIds,
    roundVisibility,
    socialNetwork,
  } = useExperimentBuilder();

  const [selectedTypeId, setSelectedTypeId] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const totalAgents = agentTypes.reduce((sum, t) => sum + t.count, 0);

  // Select first agent type by default
  const effectiveSelectedId = selectedTypeId || (agentTypes.length > 0 ? agentTypes[0].id : null);
  const selectedType = agentTypes.find(at => at.id === effectiveSelectedId) || agentTypes[0] || null;

  // Virtualize the agent type list
  const virtualizer = useVirtualizer({
    count: agentTypes.length,
    getScrollElement: () => listRef.current,
    estimateSize: () => 56,
    overscan: 8,
  });

  // If no agents defined, show warning
  if (agentTypes.length === 0) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="text-center max-w-md">
          <div
            className="inline-flex items-center justify-center w-16 h-16 rounded-full mb-4"
            style={{ background: 'var(--ss-brand-soft)' }}
          >
            <AlertCircle size={32} style={{ color: 'var(--ss-warning)' }} />
          </div>
          <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.step6.noAgentsDefined')}
          </h3>
          <p style={{ color: 'var(--ss-text-muted)' }}>
            {t('experimentBuilder.step6.goBackToStep4')}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full" style={{ minHeight: 0 }}>
      {/* Header */}
      <div
        className="rounded-lg p-4 mb-4"
        style={{
          background: 'var(--ss-brand-soft)',
          border: '1px solid var(--ss-layer-outline-strong)',
        }}
      >
        <h3 className="text-lg font-semibold" style={{ color: 'var(--ss-heading)' }}>
          {t('experimentBuilder.promptPreview.title')}
          {selectedType && ` (${t('experimentBuilder.promptPreview.agentTypeLabel', { name: selectedType.label })})`}
        </h3>
        <p className="text-sm mt-1" style={{ color: 'var(--ss-text-muted)' }}>
          {t('experimentBuilder.promptPreview.note', { n: agentTypes.length })}
        </p>
      </div>

      {/* Split layout: agent list + preview */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4" style={{ minHeight: 0 }}>
        {/* Agent type list (virtualized) */}
        <div
          className="rounded-lg overflow-hidden flex flex-col"
          style={{
            border: '1px solid var(--ss-border)',
            background: 'var(--ss-page-surface)',
          }}
        >
          <div
            className="px-3 py-2 border-b text-xs font-semibold uppercase tracking-wide"
            style={{
              borderColor: 'var(--ss-border)',
              color: 'var(--ss-text-muted)',
              background: 'var(--ss-surface-strong)',
            }}
          >
            {t('experimentBuilder.promptPreview.otherTypes')} ({agentTypes.length})
          </div>
          <div ref={listRef} className="flex-1 overflow-y-auto" style={{ maxHeight: '500px' }}>
            <div
              style={{
                height: `${virtualizer.getTotalSize()}px`,
                width: '100%',
                position: 'relative',
              }}
            >
              {virtualizer.getVirtualItems().map((virtualRow) => {
                const type = agentTypes[virtualRow.index];
                const isSelected = type.id === effectiveSelectedId;

                return (
                  <div
                    key={type.id}
                    data-index={virtualRow.index}
                    ref={virtualizer.measureElement}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      transform: `translateY(${virtualRow.start}px)`,
                      padding: '2px 6px',
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => setSelectedTypeId(type.id)}
                      className="w-full text-left p-2 rounded-md transition-colors flex items-center gap-2"
                      style={{
                        background: isSelected ? 'var(--ss-layer-active)' : 'transparent',
                        border: isSelected ? '1px solid var(--ss-layer-outline-strong)' : '1px solid transparent',
                      }}
                    >
                      <User size={14} style={{ color: 'var(--ss-text-subtle)', flexShrink: 0 }} />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium truncate" style={{ color: 'var(--ss-heading)' }}>
                          {type.label}
                        </div>
                        {type.rolePrompt && (
                          <div className="text-xs truncate" style={{ color: 'var(--ss-text-muted)' }}>
                            {type.rolePrompt.substring(0, 60)}{type.rolePrompt.length > 60 ? '...' : ''}
                          </div>
                        )}
                      </div>
                      <ChevronRight
                        size={12}
                        style={{
                          color: isSelected ? 'var(--ss-brand-primary)' : 'var(--ss-text-subtle)',
                          flexShrink: 0,
                        }}
                      />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Preview panel */}
        <div className="overflow-y-auto rounded-lg" style={{ maxHeight: '600px' }}>
          {selectedType ? (
            <PromptPreviewPanel
              agentTypeLabel={selectedType.label}
              agentTypeProfile={selectedType.userProfile || ''}
              agentTypeRolePrompt={selectedType.rolePrompt || ''}
              agentTypeProperties={selectedType.properties || {}}
              scenarioId={selectedScenarioId || ''}
              scenarioDescription={scenarioDescription}
              scenarioParams={scenarioParams}
              availableActions={availableActions}
              selectedActionIds={selectedActionIds}
              totalAgents={totalAgents}
              roundVisibility={roundVisibility}
              socialNetwork={socialNetwork}
            />
          ) : (
            <div
              className="flex items-center justify-center h-full rounded-lg"
              style={{ background: 'var(--ss-page-surface)', color: 'var(--ss-text-subtle)' }}
            >
              Select an agent type to preview
            </div>
          )}
        </div>
      </div>

      {/* Summary */}
      <div className="text-sm mt-4" style={{ color: 'var(--ss-text-muted)' }}>
        {t('experimentBuilder.step6.totalAgentsTypes', { agents: totalAgents, types: agentTypes.length })}
      </div>
    </div>
  );
};
