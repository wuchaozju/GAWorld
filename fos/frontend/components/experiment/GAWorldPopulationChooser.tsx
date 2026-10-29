/**
 * This file shows the live GAWorld resident picker in the Agents step.
 *
 * - useGAWorldPopulation supplies populations, paginated agents, selection
 *   (which survives pagination) and population generation + polling.
 * - GAWorldPopulationChooser renders it with plain researcher-facing labels
 *   (Population / City / Agents / Generate population / Selected agents).
 * - "Add selected agents" hands the chosen residents to the experiment
 *   builder together with the population provenance (city + exact GAWorld
 *   agent IDs), so GAWorld stays the source of truth.
 */

import React, { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '../ui/button';
import { RECOMMENDED_STARTER_POPULATION, STARTER_POPULATION_OPTIONS } from './gaworldStarterCohorts';
import useGAWorldPopulation, { GAWorldAgentConfig } from './useGAWorldPopulation';

export interface GAWorldPopulationSelection {
  city: string;
  agentIds: number[];
  generationJobId: string | null;
}

interface GAWorldPopulationChooserProps {
  onApply: (configs: GAWorldAgentConfig[], selection: GAWorldPopulationSelection) => void;
  onError?: (message: string) => void;
  // Legacy count-card props. The active experiment UI no longer passes them;
  // they render the pre-Phase-3 starter-cohort cards for old call sites.
  selectedCount?: number;
  isLoading?: boolean;
  onSelectCount?: (count: number) => void;
  onLoadResidents?: () => void;
}

interface PopulationChooserOptionProps {
  count: number;
  selected: boolean;
  recommended: boolean;
  onClick: (count: number) => void;
}

function PopulationChooserOption({
  count,
  selected,
  recommended,
  onClick,
}: PopulationChooserOptionProps) {
  const { t } = useTranslation();
  const label = `${count}`;
  const ariaLabel = t('experimentBuilder.step4.gaworld.populationOptionLabel', {
    count,
    defaultValue: `${count} residents`,
  });
  const description = count === 50
    ? t('experimentBuilder.step4.gaworld.populationOptionFull', {
      defaultValue: 'Full population',
    })
    : t('experimentBuilder.step4.gaworld.populationOptionStarter', {
      count,
      defaultValue: 'Starter population',
    });

  return (
    <button
      type="button"
      onClick={() => onClick(count)}
      className="rounded-lg border p-4 text-left transition-all"
      aria-pressed={selected}
      aria-label={ariaLabel}
      style={selected
        ? { background: 'var(--ss-brand-soft)', borderColor: 'var(--ss-brand-primary)' }
        : { background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-2xl font-semibold leading-none" style={{ color: 'var(--ss-heading)' }}>
            {label}
          </div>
          <div className="mt-1 text-sm" style={{ color: 'var(--ss-text-muted)' }}>
            {description}
          </div>
        </div>
        {recommended && (
          <span
            className="rounded-full px-2 py-1 text-xs font-medium"
            style={{ background: 'var(--ss-accent-warm-soft)', color: 'var(--ss-heading)' }}
          >
            {t('experimentBuilder.step4.gaworld.recommended', { defaultValue: 'Recommended' })}
          </span>
        )}
      </div>
    </button>
  );
}

export function GAWorldPopulationChooser({
  onApply,
  onError,
  selectedCount = RECOMMENDED_STARTER_POPULATION,
  isLoading = false,
  onSelectCount,
  onLoadResidents,
}: GAWorldPopulationChooserProps) {
  const { t } = useTranslation();
  const pop = useGAWorldPopulation();
  const legacyMode = typeof onLoadResidents === 'function';

  useEffect(() => {
    if (legacyMode) {
      return;
    }
    void pop.loadPopulations().catch((error: unknown) => {
      console.error('Failed to load GAWorld populations:', error);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (pop.error && onError) {
      onError(pop.error);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pop.error]);

  if (legacyMode) {
    return (
      <div
        className="rounded-lg border p-4"
        style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }}
      >
        <h4 className="font-semibold" style={{ color: 'var(--ss-heading)' }}>
          {t('experimentBuilder.step4.gaworld.populationTitle', {
            defaultValue: 'Choose starting population',
          })}
        </h4>
        <p className="mt-2 text-sm" style={{ color: 'var(--ss-text)' }}>
          {t('experimentBuilder.step4.gaworld.populationHint', {
            defaultValue: 'GAWorld includes 50 residents. Start with a smaller group for a lighter, more readable run, or load the full city.',
          })}
        </p>
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {STARTER_POPULATION_OPTIONS.map((count) => (
            <PopulationChooserOption
              key={count}
              count={count}
              selected={selectedCount === count}
              recommended={count === RECOMMENDED_STARTER_POPULATION}
              onClick={(clicked) => onSelectCount?.(clicked)}
            />
          ))}
        </div>
        <div className="mt-4 flex justify-end">
          <Button type="button" onClick={() => onLoadResidents()} disabled={isLoading}>
            {isLoading
              ? t('experimentBuilder.step4.gaworld.loadingResidents', { defaultValue: 'Loading residents...' })
              : t('experimentBuilder.step4.gaworld.loadResidents', { defaultValue: 'Load residents' })}
          </Button>
        </div>
      </div>
    );
  }

  const hasNextPage = pop.offset + pop.agents.length < pop.total;
  const hasPreviousPage = pop.offset > 0;

  const handleApply = () => {
    const configs = pop.toAgentConfigs();
    if (configs.length === 0) {
      return;
    }
    onApply(configs, {
      city: pop.city,
      agentIds: [...pop.selectedIds],
      generationJobId: pop.generation?.status === 'completed' ? pop.generation.jobId : null,
    });
  };

  const handleGenerate = () => {
    void pop.startGeneration({ size: 30 }).catch((error: unknown) => {
      console.error('Failed to start GAWorld population generation:', error);
    });
  };

  return (
    <div
      className="rounded-lg border p-4"
      style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }}
    >
      <h4 className="font-semibold" style={{ color: 'var(--ss-heading)' }}>
        {t('experimentBuilder.step4.gaworld.populationTitle', { defaultValue: 'Population' })}
      </h4>

      {pop.status === 'error' && (
        <div
          className="mt-3 rounded border p-3 text-sm"
          style={{ background: 'var(--ss-accent-warm-soft)', borderColor: 'var(--ss-layer-outline-strong)', color: 'var(--ss-heading)' }}
          role="alert"
        >
          <p>{pop.error || t('experimentBuilder.step4.gaworld.unavailable', { defaultValue: 'GAWorld backend unavailable' })}</p>
          <div className="mt-2">
            <Button type="button" onClick={() => void pop.loadPopulations().catch(() => undefined)}>
              {t('experimentBuilder.step4.gaworld.retry', { defaultValue: 'Retry' })}
            </Button>
          </div>
        </div>
      )}

      {pop.status !== 'error' && (
        <>
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-[220px_1fr]">
            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: 'var(--ss-text)' }}>
                {t('experimentBuilder.step4.gaworld.populationLabel', { defaultValue: 'Population' })}
              </label>
              <select
                value={pop.city}
                onChange={(event) => {
                  void pop.chooseCity(event.target.value).catch(() => undefined);
                }}
                className="w-full px-3 py-2 text-sm border rounded"
                style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)', color: 'var(--ss-text)' }}
              >
                {pop.populations.map((population) => (
                  <option key={population.slug || '__default__'} value={population.slug}>
                    {population.name || population.display_name || population.slug}
                    {typeof population.population === 'number' ? ` (${population.population})` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-end gap-2">
              <Button type="button" onClick={handleGenerate} disabled={pop.status === 'loading' || (pop.generation?.status === 'running' || pop.generation?.status === 'queued')}>
                {pop.generation && (pop.generation.status === 'running' || pop.generation.status === 'queued')
                  ? t('experimentBuilder.step4.gaworld.generating', { defaultValue: 'Generating population…' })
                  : t('experimentBuilder.step4.gaworld.generate', { defaultValue: 'Generate population' })}
              </Button>
              {pop.generation && (
                <span className="text-sm" style={{ color: 'var(--ss-text-muted)' }}>
                  {pop.generation.status}
                </span>
              )}
            </div>
          </div>

          <div className="mt-4">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-medium" style={{ color: 'var(--ss-text)' }}>
                {t('experimentBuilder.step4.gaworld.agentsLabel', { defaultValue: 'Agents' })}
              </label>
              <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--ss-text-muted)' }}>
                <button
                  type="button"
                  className="px-2 py-1 border rounded disabled:opacity-40"
                  disabled={!hasPreviousPage || pop.status === 'loading'}
                  onClick={() => void pop.loadAgents({ offset: Math.max(0, pop.offset - pop.limit) }).catch(() => undefined)}
                >
                  {t('experimentBuilder.step4.gaworld.previousPage', { defaultValue: 'Previous' })}
                </button>
                <span>
                  {pop.total === 0 ? 0 : pop.offset + 1}–{pop.offset + pop.agents.length} / {pop.total}
                </span>
                <button
                  type="button"
                  className="px-2 py-1 border rounded disabled:opacity-40"
                  disabled={!hasNextPage || pop.status === 'loading'}
                  onClick={() => void pop.loadAgents({ offset: pop.offset + pop.limit }).catch(() => undefined)}
                >
                  {t('experimentBuilder.step4.gaworld.nextPage', { defaultValue: 'Next' })}
                </button>
              </div>
            </div>

            <div className="mt-2 max-h-64 overflow-y-auto rounded border" style={{ borderColor: 'var(--ss-border)' }}>
              {pop.agents.map((agent) => {
                const selected = pop.isSelected(agent.id);
                return (
                  <label
                    key={agent.id}
                    className="flex items-center gap-3 px-3 py-2 text-sm cursor-pointer"
                    style={{ borderTop: '1px solid var(--ss-border)', background: selected ? 'var(--ss-brand-soft)' : 'transparent' }}
                  >
                    <input type="checkbox" checked={selected} onChange={() => pop.toggle(agent.id)} />
                    <span style={{ color: 'var(--ss-heading)' }}>{agent.name}</span>
                    {typeof agent.age === 'number' && <span style={{ color: 'var(--ss-text-muted)' }}>{agent.age}</span>}
                    {typeof agent.job === 'string' && agent.job && <span style={{ color: 'var(--ss-text-muted)' }}>{agent.job}</span>}
                  </label>
                );
              })}
              {pop.agents.length === 0 && pop.status !== 'loading' && (
                <div className="px-3 py-4 text-sm" style={{ color: 'var(--ss-text-muted)' }}>
                  {t('experimentBuilder.step4.gaworld.noAgents', { defaultValue: 'No residents on this page.' })}
                </div>
              )}
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between">
            <span className="text-sm" style={{ color: 'var(--ss-text-muted)' }}>
              {t('experimentBuilder.step4.gaworld.selectedAgents', {
                defaultValue: 'Selected agents: {{count}}',
                count: pop.selectedIds.length,
              })}
            </span>
            <Button type="button" onClick={handleApply} disabled={pop.selectedIds.length === 0}>
              {t('experimentBuilder.step4.gaworld.addSelected', { defaultValue: 'Add selected agents' })}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

export default GAWorldPopulationChooser;
