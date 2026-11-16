/**
 * Step 2 Demographics Editor
 *
 * Advanced demographic-based agent generation UI.
 * Allows users to define custom demographic dimensions, categories,
 * archetypes with probabilities, and traits.
 *
 * This is the flexible, user-customizable demographic generation
 * that was used in the original SimulationWizard design.
 */

import React, { useState, useEffect } from 'react';
import { Loader2, Sparkles, Plus, Minus, Trash2, RefreshCw } from 'lucide-react';
import type { Agent } from '../../types';
import type { Provider } from '../../services/providers';

// =============================================================================
// Types
// =============================================================================

export interface Demographic {
  id: string;
  name: string;
  categories: string[];
}

export interface Archetype {
  id: string;
  attributes: Record<string, string>;
  label: string;
  probability: number;
}

export interface TraitConfig {
  id: string;
  name: string;
  mean: number;
  std: number;
}

export interface LLMAllocation {
  providerId: number;
  providerName: string;
  modelName: string;
  percentage: number;
}

export interface Step2DemographicsEditorProps {
  demographics: Demographic[];
  archetypes: Archetype[];
  traits: TraitConfig[];
  genCount: number;
  isGenerating: boolean;
  onAddDemographic: () => void;
  onRemoveDemographic: (id: string) => void;
  onUpdateDemographicName: (id: string, name: string) => void;
  onUpdateDemographicCategories: (id: string, categories: string) => void;
  onUpdateCategoryName: (demoId: string, catIndex: number, value: string) => void;
  onAddCategory: (demoId: string) => void;
  onRemoveCategory: (demoId: string, catIndex: number) => void;
  onUpdateArchetypeProbability: (archId: string, newProb: number) => void;
  onNormalizeProbabilities: () => void;
  onAddTrait: () => void;
  onRemoveTrait: (id: string) => void;
  onUpdateTrait: (id: string, field: keyof TraitConfig, value: string | number) => void;
  onSetGenCount: (count: number) => void;
  onGenerateAgents: () => void;
  customAgents: Agent[];
  setCustomAgents: (agents: Agent[]) => void;
  importError: string | null;
  // LLM Distribution props
  llmAllocations?: LLMAllocation[];
  onAddLlmAllocation?: () => void;
  onRemoveLlmAllocation?: (index: number) => void;
  onUpdateLlmAllocation?: (index: number, field: keyof LLMAllocation, value: number | string) => void;
  onApplyLlmDistribution?: () => void;
  availableProviders?: Provider[];  // Providers from parent
  providersLoading?: boolean;       // Loading state from parent
  useTranslation?: boolean; // If true, use t() function for labels
  t?: (key: string, options?: Record<string, unknown>) => string;
}

// =============================================================================
// Helper Component: Step2AgentsPreview
// =============================================================================

interface Step2AgentsPreviewProps {
  agents: Agent[];
  onClear: () => void;
  t?: (key: string, options?: Record<string, unknown>) => string;
}

const Step2AgentsPreview: React.FC<Step2AgentsPreviewProps> = ({ agents, onClear, t }) => {
  const getText = (key: string, fallback: string, options?: Record<string, unknown>) => {
    const translated = t?.(key, options);
    if (!translated || translated === key) {
      return fallback.replace(/\{\{\s*(\w+)\s*\}\}/g, (_match, token) => String(options?.[token] ?? ''));
    }
    return translated;
  };

  return (
    <div className="rounded-lg p-4" style={{ border: '1px solid var(--ss-border)', background: 'var(--ss-page-surface-muted)' }}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-bold" style={{ color: 'var(--ss-heading)' }}>
          {getText('wizard.step2.generatedAgents', 'Generated {{count}} agents', { count: agents.length })}
        </h4>
        <button
          onClick={onClear}
          className="text-xs px-2 py-1 rounded"
          style={{ background: 'var(--ss-danger-soft)', color: 'var(--ss-danger)' }}
        >
          {getText('wizard.step2.clearReset', 'Clear & Reset')}
        </button>
      </div>
      <div className="max-h-48 overflow-y-auto space-y-2">
        {agents.map((agent) => (
          <div key={agent.id} className="flex items-center gap-3 p-2 rounded text-sm" style={{ background: 'var(--ss-page-surface)', border: '1px solid var(--ss-border)' }}>
            <img
              src={agent.avatarUrl}
              alt={agent.name}
              className="w-8 h-8 rounded-full"
              style={{ background: 'var(--ss-page-surface-muted)' }}
            />
            <div className="flex-1 min-w-0">
              <div className="font-medium truncate" style={{ color: 'var(--ss-heading)' }}>{agent.name}</div>
              <div className="text-xs truncate" style={{ color: 'var(--ss-text-muted)' }}>{agent.profile}</div>
            </div>
            {agent.llmConfig && (
              <div className="text-xs" style={{ color: 'var(--ss-text-subtle)' }}>
                {agent.llmConfig.model || agent.llmConfig.provider || 'AI'}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

// =============================================================================
// Main Component: Step2DemographicsEditor
// =============================================================================

export const Step2DemographicsEditor: React.FC<Step2DemographicsEditorProps> = ({
  demographics,
  archetypes,
  traits,
  genCount,
  isGenerating,
  onAddDemographic,
  onRemoveDemographic,
  onUpdateDemographicName,
  onUpdateDemographicCategories,
  onUpdateCategoryName,
  onAddCategory,
  onRemoveCategory,
  onUpdateArchetypeProbability,
  onNormalizeProbabilities,
  onAddTrait,
  onRemoveTrait,
  onUpdateTrait,
  onSetGenCount,
  onGenerateAgents,
  customAgents,
  setCustomAgents,
  importError,
  llmAllocations = [],
  onAddLlmAllocation,
  onRemoveLlmAllocation,
  onUpdateLlmAllocation,
  onApplyLlmDistribution,
  availableProviders: propAvailableProviders = [],  // From parent
  providersLoading: propProvidersLoading = false,   // From parent
  useTranslation = false,
  t,
}) => {
  const getText = (key: string, fallback: string, options?: Record<string, unknown>) => {
    if (!(useTranslation && t)) {
      return fallback.replace(/\{\{\s*(\w+)\s*\}\}/g, (_match, token) => String(options?.[token] ?? ''));
    }

    const translated = t(key, options);
    if (!translated || translated === key) {
      return fallback.replace(/\{\{\s*(\w+)\s*\}\}/g, (_match, token) => String(options?.[token] ?? ''));
    }

    return translated;
  };

  // Use providers from props (managed by parent)
  const availableProviders = propAvailableProviders;
  const providersLoading = propProvidersLoading;

  // Calculate total percentage and validation
  const totalPercentage = llmAllocations.reduce((sum, a) => sum + a.percentage, 0);
  const isLlmDistributionValid = llmAllocations.length === 0 || totalPercentage === 100;

  const inputStyle: React.CSSProperties = {
    background: 'var(--ss-page-surface)',
    border: '1px solid var(--ss-border-strong)',
    color: 'var(--ss-text)',
  };

  return (
    <div className="flex-1 flex flex-col gap-4 overflow-y-auto">
      {/* Demographics Configuration */}
      <div className="rounded-lg p-4" style={{ border: '1px solid var(--ss-border)' }}>
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-bold" style={{ color: 'var(--ss-heading)' }}>
            {getText('wizard.step2.demographics', 'Demographics')}
          </h4>
          <button
            onClick={onAddDemographic}
            className="text-xs px-2 py-1 rounded flex items-center gap-1"
            style={{ background: 'var(--ss-page-surface-muted)', color: 'var(--ss-text)' }}
          >
            <Plus size={14} /> {getText('wizard.step2.addDimension', 'Add Dimension')}
          </button>
        </div>
        <div className="space-y-3">
          {demographics.map((demo) => (
            <div key={demo.id} className="rounded p-3" style={{ border: '1px solid var(--ss-border)', background: 'var(--ss-page-surface-muted)' }}>
              <div className="flex items-center gap-2 mb-2">
                <input
                  type="text"
                  value={demo.name}
                  onChange={(e) => onUpdateDemographicName(demo.id, e.target.value)}
                  placeholder={getText('wizard.step2.dimensionNamePlaceholder', 'Dimension name (e.g., Age)')}
                  className="flex-1 px-2 py-1 rounded text-sm"
                  style={inputStyle}
                />
                {demographics.length > 1 && (
                  <button
                    onClick={() => onRemoveDemographic(demo.id)}
                    className="p-1 rounded"
                    style={{ color: 'var(--ss-danger)' }}
                  >
                    <Minus size={16} />
                  </button>
                )}
              </div>
              <div className="space-y-1">
                <div className="text-xs" style={{ color: 'var(--ss-text-muted)' }}>
                  {getText('wizard.step2.categoriesLabel', 'Categories (comma separated):')}
                </div>
                {demo.categories.map((cat, catIdx) => (
                  <div key={catIdx} className="flex items-center gap-2">
                    <input
                      type="text"
                      value={cat}
                      onChange={(e) => onUpdateCategoryName(demo.id, catIdx, e.target.value)}
                      className="flex-1 px-2 py-1 rounded text-sm"
                      style={inputStyle}
                    />
                    {demo.categories.length > 1 && (
                      <button
                        onClick={() => onRemoveCategory(demo.id, catIdx)}
                        className="p-1"
                        style={{ color: 'var(--ss-danger)' }}
                      >
                        <Minus size={14} />
                      </button>
                    )}
                  </div>
                ))}
                <button
                  onClick={() => onAddCategory(demo.id)}
                  className="text-xs px-2 py-1 rounded flex items-center gap-1"
                  style={{ background: 'var(--ss-page-surface)', color: 'var(--ss-text-muted)' }}
                >
                  <Plus size={12} /> {getText('wizard.step2.addCategory', 'Add Category')}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Generated Archetypes Preview */}
      {archetypes.length > 0 && (
        <div className="rounded-lg p-4" style={{ border: '1px solid var(--ss-border)' }}>
          <div className="flex items-center justify-between mb-3">
            <div>
              <h4 className="text-sm font-bold" style={{ color: 'var(--ss-heading)' }}>
                {getText('wizard.step2.archetypes', 'Archetypes: {{count}}').replace('{{count}}', String(archetypes.length))}
              </h4>
              <span className="text-xs" style={{ color: 'var(--ss-text-muted)' }}>
                {getText('wizard.step2.archetypesHint', 'Archetypes × Demographic Dimensions = Agent Combinations')}
              </span>
            </div>
            <div className="text-right">
              <div className="text-xs" style={{ color: 'var(--ss-text-muted)' }}>
                {getText('wizard.step2.totalProbability', 'Total Probability')}: {' '}
                <span className="font-bold" style={{ color: Math.abs(archetypes.reduce((sum, a) => sum + a.probability, 0) - 1.0) < 0.01 ? 'var(--ss-success)' : 'var(--ss-warning)' }}>
                  {archetypes.reduce((sum, a) => sum + a.probability, 0).toFixed(2)}
                </span> {getText('wizard.step2.shouldBeOne', '(should be 1.0)')}
              </div>
              <button
                onClick={onNormalizeProbabilities}
                className="text-[10px] px-2 py-1 rounded mt-1"
                style={{ background: 'var(--ss-page-surface-muted)', color: 'var(--ss-text-muted)' }}
              >
                {getText('wizard.step2.normalizeAll', 'Normalize All')}
              </button>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2 max-h-48 overflow-y-auto">
            {archetypes.map((arch) => (
              <div key={arch.id} className="p-2 rounded text-xs" style={{ background: 'var(--ss-page-surface-muted)', border: '1px solid var(--ss-border)' }}>
                <div className="font-medium truncate mb-1" style={{ color: 'var(--ss-heading)' }} title={arch.label}>
                  {arch.label}
                </div>
                <div className="flex items-center gap-2">
                  <label style={{ color: 'var(--ss-text-muted)' }}>{getText('wizard.step2.probability', 'Probability')}:</label>
                  <input
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    value={arch.probability.toFixed(2)}
                    onChange={(e) => onUpdateArchetypeProbability(arch.id, parseFloat(e.target.value) || 0)}
                    className="flex-1 px-1 py-0.5 rounded text-xs text-right"
                    style={inputStyle}
                  />
                  <span style={{ color: 'var(--ss-text-muted)' }}>({(arch.probability * 100).toFixed(0)}%)</span>
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs mt-2" style={{ color: 'var(--ss-text-muted)' }}>
            {getText('wizard.step2.modifyProbabilityHint', 'After modifying any probability, others will auto-adjust proportionally to maintain sum = 1.0')}
          </p>
        </div>
      )}

      {/* Traits Configuration */}
      <div className="rounded-lg p-4" style={{ border: '1px solid var(--ss-border)' }}>
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-bold" style={{ color: 'var(--ss-heading)' }}>
            {getText('wizard.step2.traits', 'Traits')}
          </h4>
          <button
            onClick={onAddTrait}
            className="text-xs px-2 py-1 rounded flex items-center gap-1"
            style={{ background: 'var(--ss-page-surface-muted)', color: 'var(--ss-text)' }}
          >
            <Plus size={14} /> {getText('wizard.step2.addTrait', 'Add Trait')}
          </button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {traits.map((trait) => (
            <div key={trait.id} className="rounded p-2" style={{ border: '1px solid var(--ss-border)', background: 'var(--ss-page-surface-muted)' }}>
              <div className="flex items-center gap-2 mb-2">
                <input
                  type="text"
                  value={trait.name}
                  onChange={(e) => onUpdateTrait(trait.id, 'name', e.target.value)}
                  className="flex-1 px-2 py-1 rounded text-sm font-medium"
                  style={inputStyle}
                />
                {traits.length > 1 && (
                  <button
                    onClick={() => onRemoveTrait(trait.id)}
                    className="p-1 rounded"
                    style={{ color: 'var(--ss-danger)' }}
                  >
                    <Minus size={16} />
                  </button>
                )}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px]" style={{ color: 'var(--ss-text-muted)' }}>{getText('wizard.step2.mean', 'Mean')}</label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={trait.mean}
                    onChange={(e) => onUpdateTrait(trait.id, 'mean', parseInt(e.target.value) || 0)}
                    className="w-full px-2 py-1 rounded text-sm"
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label className="text-[10px]" style={{ color: 'var(--ss-text-muted)' }}>{getText('wizard.step2.std', 'Std')}</label>
                  <input
                    type="number"
                    min="0"
                    max="50"
                    value={trait.std}
                    onChange={(e) => onUpdateTrait(trait.id, 'std', parseInt(e.target.value) || 0)}
                    className="w-full px-2 py-1 rounded text-sm"
                    style={inputStyle}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
        <p className="text-xs mt-2" style={{ color: 'var(--ss-text-muted)' }}>
          {getText('wizard.step2.traitsHint', 'Traits will use Gaussian distribution (mean ± std), limited to 0-100 range.')}
        </p>
      </div>

      {/* LLM Distribution Section - Configure before generating */}
      <div className="rounded-lg p-4" style={{ border: '1px solid var(--ss-border)' }}>
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-bold" style={{ color: 'var(--ss-heading)' }}>
            {getText('wizard.llmDistribution.title', 'LLM Distribution')}
          </h4>
        </div>

        {providersLoading ? (
          <div className="flex items-center justify-center py-4" style={{ color: 'var(--ss-text-muted)' }}>
            <Loader2 size={18} className="animate-spin mr-2" />
            {getText('wizard.llmDistribution.loadingProviders', 'Loading providers...')}
          </div>
        ) : availableProviders.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-4" style={{ color: 'var(--ss-text-muted)' }}>
            <p className="text-sm">{getText('wizard.llmDistribution.noProviders', 'No LLM providers configured.')}</p>
            <p className="text-xs mt-1">{getText('wizard.llmDistribution.configureInSettings', 'Please configure providers in Settings.')}</p>
          </div>
        ) : (
          <>
            <div className="space-y-2 mb-3">
              {llmAllocations && llmAllocations.map((allocation, index) => (
                <div key={index} className="flex items-center gap-2 p-2 rounded" style={{ background: 'var(--ss-page-surface-muted)' }}>
                  <select
                    value={allocation.providerId}
                    onChange={(e) => onUpdateLlmAllocation && onUpdateLlmAllocation(index, 'providerId', Number(e.target.value))}
                    className="flex-1 min-w-[200px] px-2 py-1 rounded text-sm"
                    style={inputStyle}
                  >
                    {availableProviders && availableProviders.map(p => (
                      <option key={p.id} value={p.id}>
                        {p.provider} - {p.model}
                      </option>
                    ))}
                  </select>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={allocation.percentage || ''}
                    onChange={(e) => onUpdateLlmAllocation && onUpdateLlmAllocation(index, 'percentage', Math.min(100, Math.max(0, parseInt(e.target.value) || 1)))}
                    className="w-20 px-2 py-1 rounded text-sm text-center"
                    style={inputStyle}
                    placeholder="%"
                  />
                  <span className="text-sm" style={{ color: 'var(--ss-text-muted)' }}>%</span>
                  {onRemoveLlmAllocation && (
                    <button
                      onClick={() => onRemoveLlmAllocation(index)}
                      style={{ color: 'var(--ss-danger)' }}
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="flex items-center gap-2 mb-2">
              {onAddLlmAllocation && (
                <button
                  onClick={onAddLlmAllocation}
                  disabled={availableProviders.length === 0}
                  className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm"
                  style={{
                    background: 'var(--ss-brand-primary)',
                    color: '#fff',
                    opacity: availableProviders.length === 0 ? 0.5 : 1,
                  }}
                >
                  <Plus size={14} />
                  {getText('wizard.llmDistribution.addLlm', 'Add LLM')}
                </button>
              )}
              {llmAllocations && llmAllocations.length > 0 && (
                <div className="space-y-2">
                  <div className="text-sm font-medium" style={{ color: isLlmDistributionValid ? 'var(--ss-success)' : 'var(--ss-danger)' }}>
                    {isLlmDistributionValid ? (
                      <span>{getText('wizard.llmDistribution.totalValid', 'Total: 100% ✓')}</span>
                    ) : (
                      <span>{getText('wizard.llmDistribution.mustEqual100', 'Total must equal 100% (currently {{count}}%)', { count: totalPercentage })}</span>
                    )}
                  </div>
                  {llmAllocations && llmAllocations.length > 0 && (
                    <p className="text-xs mt-2" style={{ color: 'var(--ss-text-muted)' }}>
                      {getText('wizard.llmDistribution.distributionHint',
                        'Distribution will be applied when agents are generated.')}
                    </p>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Generation Settings */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4 rounded-lg" style={{ background: 'var(--ss-brand-soft)', border: '1px solid var(--ss-brand-primary)' }}>
        <div>
          <label className="block text-xs font-bold mb-2" style={{ color: 'var(--ss-brand-on)' }}>
            {getText('wizard.step2.generateCount', 'Generate Count')}
          </label>
          <input
            type="number"
            min="1"
            value={genCount}
            onChange={(e) => onSetGenCount(Math.max(1, parseInt(e.target.value) || 1))}
            className="w-full px-3 py-2 rounded text-sm"
            style={inputStyle}
          />
        </div>
        <div className="flex items-end">
          <button
            onClick={onGenerateAgents}
            disabled={isGenerating}
            className="px-6 py-2 text-white text-sm font-bold rounded-lg flex items-center gap-2 disabled:opacity-50"
            style={{ background: 'var(--ss-brand-primary)' }}
          >
            {isGenerating ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Sparkles size={16} />
            )}
            {getText('wizard.step2.startGeneration', 'Start Generating')}
          </button>
        </div>
      </div>

      {importError && (
        <div className="p-3 text-xs rounded" style={{ background: 'var(--ss-danger-soft)', color: 'var(--ss-danger)', border: '1px solid var(--ss-danger)' }}>
          {importError}
        </div>
      )}

      {/* Preview for Generated Agents */}
      {customAgents.length > 0 ? (
        <Step2AgentsPreview
          agents={customAgents}
          onClear={() => setCustomAgents([])}
          t={t}
        />
      ) : (
        <div className="text-xs text-center py-2" style={{ color: 'var(--ss-text-muted)' }}>
          {getText('wizard.step2.noAgentsGenerated', 'No agents generated yet.')}
        </div>
      )}
    </div>
  );
};

export default Step2DemographicsEditor;
