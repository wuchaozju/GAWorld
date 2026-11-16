/**
 * LLM Routing Policy section (Phase 4).
 *
 * Shows the experiment default assignment ("Uses default" vs per-agent
 * overrides are shown on each agent card), a failure-policy selector
 * (pause_and_ask | fail | ordered_fallback) and, for ordered_fallback, an
 * explicit ordered fallback list. Provider IDs and model names only —
 * credentials never appear here.
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { useExperimentBuilder } from '../../store/experiment-builder';

const POLICIES: Array<'pause_and_ask' | 'fail' | 'ordered_fallback'> = [
  'pause_and_ask',
  'fail',
  'ordered_fallback',
];

export const LlmRoutingPolicy: React.FC = () => {
  const { t } = useTranslation();
  const rawProviders = useExperimentBuilder((s) => s.llmProviders);
  const llmProviders = Array.isArray(rawProviders) ? rawProviders : [];
  const selectedProviderId = useExperimentBuilder((s) => s.selectedProviderId);
  const failurePolicy = useExperimentBuilder((s) => s.failurePolicy);
  const setFailurePolicy = useExperimentBuilder((s) => s.setFailurePolicy);
  const fallbackProviderIds = useExperimentBuilder((s) => s.fallbackProviderIds);
  const setFallbackProviderIds = useExperimentBuilder((s) => s.setFallbackProviderIds);

  if (llmProviders.length === 0) {
    return null;
  }

  const defaultProvider = llmProviders.find((p) => p.id === selectedProviderId);
  const defaultLabel = defaultProvider
    ? `${defaultProvider.name} / ${defaultProvider.model || 'default'}`
    : t('experimentBuilder.llmRouting.usesBackendDefault');

  const toggleFallback = (id: number) => {
    if (fallbackProviderIds.includes(id)) {
      setFallbackProviderIds(fallbackProviderIds.filter((x) => x !== id));
    } else {
      setFallbackProviderIds([...fallbackProviderIds, id]);
    }
  };

  const moveFallback = (index: number, delta: number) => {
    const next = [...fallbackProviderIds];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setFallbackProviderIds(next);
  };

  const policyHint =
    failurePolicy === 'pause_and_ask'
      ? t('experimentBuilder.llmRouting.hintPauseAndAsk')
      : failurePolicy === 'fail'
        ? t('experimentBuilder.llmRouting.hintFail')
        : t('experimentBuilder.llmRouting.hintOrderedFallback');

  return (
    <section
      data-testid="llm-routing-policy"
      className="mt-6 rounded-lg p-4"
      style={{ border: '1px solid var(--ss-border)', background: 'var(--ss-surface-2)' }}
    >
      <h3 className="text-sm font-semibold mb-1" style={{ color: 'var(--ss-heading)' }}>
        {t('experimentBuilder.llmRouting.title')}
      </h3>
      <p className="text-xs mb-3" style={{ color: 'var(--ss-text-subtle)' }}>
        {t('experimentBuilder.llmRouting.defaultLabel')}: <strong>{defaultLabel}</strong>
      </p>

      <label className="block text-xs mb-1" htmlFor="llm-failure-policy">
        {t('experimentBuilder.llmRouting.policyLabel')}
      </label>
      <select
        id="llm-failure-policy"
        value={failurePolicy}
        onChange={(e) => setFailurePolicy(e.target.value as typeof failurePolicy)}
        className="text-sm rounded px-2 py-1 mb-1"
        style={{ border: '1px solid var(--ss-border)', background: 'var(--ss-surface)', color: 'var(--ss-text)' }}
      >
        {POLICIES.map((p) => (
          <option key={p} value={p}>
            {t(`experimentBuilder.llmRouting.policy_${p}`)}
          </option>
        ))}
      </select>
      <p className="text-xs mb-3" style={{ color: 'var(--ss-text-subtle)' }}>
        {policyHint}
      </p>

      {failurePolicy === 'ordered_fallback' && (
        <div>
          <p className="text-xs mb-2" style={{ color: 'var(--ss-text-subtle)' }}>
            {t('experimentBuilder.llmRouting.fallbackHint')}
          </p>
          {llmProviders.map((p) => {
            const index = fallbackProviderIds.indexOf(p.id);
            const inList = index >= 0;
            return (
              <div key={p.id} className="flex items-center gap-2 mb-1 text-sm">
                <button
                  type="button"
                  onClick={() => toggleFallback(p.id)}
                  className="rounded px-2 py-0.5 text-xs"
                  style={{
                    border: '1px solid var(--ss-border)',
                    background: inList ? 'var(--ss-accent, var(--ss-surface-2))' : 'var(--ss-surface)',
                    color: 'var(--ss-text)',
                  }}
                >
                  {inList ? `${index + 1}. ` : '+ '}
                  {p.name} / {p.model || 'default'}
                </button>
                {inList && (
                  <>
                    <button type="button" aria-label={t('experimentBuilder.llmRouting.moveUp')} onClick={() => moveFallback(index, -1)} style={{ color: 'var(--ss-text-subtle)' }}>↑</button>
                    <button type="button" aria-label={t('experimentBuilder.llmRouting.moveDown')} onClick={() => moveFallback(index, 1)} style={{ color: 'var(--ss-text-subtle)' }}>↓</button>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};

export default LlmRoutingPolicy;
