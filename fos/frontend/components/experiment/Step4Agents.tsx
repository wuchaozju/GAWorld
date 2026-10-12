/**
 * Step 4: Agent Design
 *
 * Users design agents through three modes:
 * - Manual: Define agent types manually (for small experiments)
 * - Demographic: Generate agents from demographic variables with custom dimensions
 * - Import: Upload CSV/JSON files
 *
 * The demographic mode uses the flexible user-customizable approach
 * from the original SimulationWizard design.
 */

import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useExperimentBuilder, ManualAgentType, LLMProvider } from '../../store/experiment-builder';
import { generateAgentsWithDemographics, isZh } from '../../store/helpers';
import { Step2DemographicsEditor, Demographic, Archetype, TraitConfig, LLMAllocation } from '../wizard/Step2DemographicsEditor';
import type { Agent } from '../../types';
import { applyLlmDistribution } from '../../utils/llmDistribution';
import { Button } from '../ui/button';
import { ChevronDown } from 'lucide-react';
import GAWorldPopulationChooser from './GAWorldPopulationChooser';
import { getGAWorldStarterCohortIds, RECOMMENDED_STARTER_POPULATION } from './gaworldStarterCohorts';
import { isPolicyCascadeScenario } from '../../utils/policyCascade';

type TierValue = string;

// =============================================================================
// Helper Functions
// =============================================================================

const generateId = () => `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

// Tier property key constant - use this instead of hardcoded strings
const TIER_PROPERTY_KEY = 'tier_level';

const normalizeTierValue = (value: string): TierValue => {
  const normalized = value.toLowerCase().replace(/[\s_-]/g, '');
  // Check for English tier keywords
  if (normalized.includes('top') || normalized.includes('high')) return 'top';
  if (normalized.includes('mid') || normalized.includes('middle')) return 'mid';
  if (normalized.includes('low') || normalized.includes('base')) return 'low';
  // Check for Chinese tier keywords (for backwards compatibility with existing data)
  if (value.includes('高层') || value.includes('高级')) return 'top';
  if (value.includes('中层') || value.includes('中级')) return 'mid';
  if (value.includes('基层') || value.includes('低级')) return 'low';
  return '';
};

const inferTierFromAgent = (agent: Partial<ManualAgentType>): TierValue => {
  const explicitTier = normalizeTierValue(String(agent.properties?.tier || ''));
  if (explicitTier) return explicitTier;
  return normalizeTierValue([
    agent.label || '',
    agent.rolePrompt || '',
    agent.userProfile || '',
  ].join(' '));
};

const parseTierOrder = (rawValue: unknown): string[] => {
  const values = Array.isArray(rawValue)
    ? rawValue.map((item) => String(item).trim())
    : String(rawValue || 'top, mid, low')
      .split(/[\n,，]+/)
      .map((item) => item.trim());

  const cleaned: string[] = [];
  const seen = new Set<string>();
  values.forEach((value) => {
    if (!value) return;
    const key = value.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    cleaned.push(value);
  });
  return cleaned.length > 0 ? cleaned : ['top', 'mid', 'low'];
};

const inferOrderedTier = (agent: Partial<ManualAgentType>, tierOrder: string[]): string => {
  const explicit = String(agent.properties?.tier || '').trim();
  if (explicit) {
    const matched = tierOrder.find((tier) => tier.toLowerCase() === explicit.toLowerCase());
    if (matched) return matched;
  }

  // Check for tier using language-agnostic property key
  const profileTier = String(agent.properties?.[TIER_PROPERTY_KEY] || agent.properties?.tier || '').trim();
  if (profileTier) {
    const matched = tierOrder.find((tier) => tier.toLowerCase() === profileTier.toLowerCase());
    if (matched) return matched;
  }

  const normalizedTier = inferTierFromAgent(agent);
  if (!normalizedTier) return '';
  const matched = tierOrder.find((tier) => normalizeTierValue(tier) === normalizedTier);
  return matched || '';
};

const defaultTierName = (index: number): string => {
  if (index === 0) return 'top';
  if (index === 1) return 'mid';
  if (index === 2) return 'low';
  return `level_${index + 1}`;
};

const resizeTierOrder = (current: string[], count: number): string[] => {
  const nextCount = Math.max(2, count || 2);
  const next: string[] = [];
  for (let i = 0; i < nextCount; i += 1) {
    next.push(current[i] || defaultTierName(i));
  }
  return next;
};

const isPolicyCascadeScenarioData = (scenario: {
  id?: string;
  sceneType?: string;
} | null | undefined): boolean => {
  return isPolicyCascadeScenario(scenario);
};

// Generate archetypes from demographics (cross-product)
const generateArchetypes = (demographics: Demographic[]): Archetype[] => {
  if (demographics.length === 0) return [];

  let combinations: Record<string, string>[] = demographics[0].categories.map((cat) => ({
    [demographics[0].name]: cat,
  }));

  for (let i = 1; i < demographics.length; i++) {
    const demo = demographics[i];
    const newCombos: Record<string, string>[] = [];
    for (const combo of combinations) {
      for (const cat of demo.categories) {
        newCombos.push({ ...combo, [demo.name]: cat });
      }
    }
    combinations = newCombos;
  }

  const equalProb = 1 / combinations.length;
  return combinations.map((attrs, idx) => ({
    id: `arch_${idx}`,
    attributes: attrs,
    label: Object.entries(attrs)
      .map(([k, v]) => `${k}: ${v}`)
      .join(' | '),
    probability: equalProb,
  }));
};

// =============================================================================
// Component
// =============================================================================

export const Step4Agents: React.FC = () => {
  const { t } = useTranslation();
  const {
    agentMode,
    setAgentMode,
    agentTypes,
    addAgentType,
    removeAgentType,
    updateAgentType,
    llmProviders,
    selectedProviderId,
    setSelectedProviderId,
    scenarioParams,
    setScenarioParams,
    loadProviders,
    getSelectedProviderId,
    selectedScenarioId,
    selectedScenarioData,
    loadDefaultAgentsForScenario,
  } = useExperimentBuilder();

  // Load providers on mount
  useEffect(() => {
    if (llmProviders.length === 0) {
      loadProviders();
    }
  }, []);

  // ==================== Manual Mode State ====================

  const [newAgentType, setNewAgentType] = useState<ManualAgentType>({
    id: '',
    label: '',
    count: 1,
    rolePrompt: '',
    userProfile: '',
    properties: { tier: '' },
    providerId: null,
  });

  // ==================== Demographic Mode State ====================

  const [demographics, setDemographics] = useState<Demographic[]>([]);
  const [archetypes, setArchetypes] = useState<Archetype[]>([]);
  const [traits, setTraits] = useState<TraitConfig[]>(() => [
    { id: generateId(), name: t('wizard.defaults.traits.trust'), mean: 50, std: 15 }
  ]);
  const [propertyDrafts, setPropertyDrafts] = useState<Record<string, Array<{ id: string; originalKey: string; key: string; value: string }>>>({});
  const [genCount, setGenCount] = useState(5);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedAgents, setGeneratedAgents] = useState<Agent[]>([]);
  const [importError, setImportError] = useState<string | null>(null);
  const [tierOrderDraft, setTierOrderDraft] = useState<string[]>(['top', 'mid', 'low']);
  const [llmAllocations, setLlmAllocations] = useState<LLMAllocation[]>([]);
  const [selectedGAWorldPopulation, setSelectedGAWorldPopulation] = useState<number>(RECOMMENDED_STARTER_POPULATION);
  const [isLoadingGAWorldPopulation, setIsLoadingGAWorldPopulation] = useState(false);

  // ==================== Agent List UI State ====================
  const [isAgentListOpen, setIsAgentListOpen] = useState(false);
  const [expandedAgentId, setExpandedAgentId] = useState<string | null>(null);
  const agentListRef = useRef<HTMLDivElement>(null);

  const scenarioId = selectedScenarioData?.id || selectedScenarioId || '';
  const showTierControls = isPolicyCascadeScenarioData(selectedScenarioData || { id: scenarioId });
  const tierOrder = useMemo(() => parseTierOrder(scenarioParams?.tier_order), [scenarioParams]);
  const cascadeMode = String(scenarioParams?.cascade_mode || 'strict_cascade');
  const tierOrderDraftValid =
    tierOrderDraft.length >= 2 &&
    tierOrderDraft.every((tier) => tier.trim()) &&
    new Set(tierOrderDraft.map((tier) => tier.trim().toLowerCase())).size === tierOrderDraft.length;
  const hasPendingTierDraft =
    tierOrderDraft.length !== tierOrder.length ||
    tierOrderDraft.some((tier, index) => tier.trim().toLowerCase() !== String(tierOrder[index] || '').trim().toLowerCase());

  useEffect(() => {
    if (!showTierControls) return;
    if (scenarioParams?.tier_order) return;
    setScenarioParams({ ...scenarioParams, tier_order: ['top', 'mid', 'low'] });
  }, [showTierControls, scenarioParams, setScenarioParams]);

  useEffect(() => {
    if (!showTierControls) return;
    setTierOrderDraft(tierOrder);
  }, [showTierControls, tierOrder]);

  // Initialize demographics on first render
  useEffect(() => {
    if (showTierControls) {
      const tierLabel = t('wizard.defaults.tierLabel');
      const alreadyTier = demographics.length === 1 && demographics[0]?.name === tierLabel;
      const sameCategories = alreadyTier && demographics[0]?.categories.join('|') === tierOrder.join('|');
      if (!sameCategories) {
        setDemographics([{ id: generateId(), name: tierLabel, categories: tierOrder }]);
      }
      if (genCount < tierOrder.length) {
        setGenCount(tierOrder.length);
      }
      return;
    }

    const hasPolicyOnlyDemographics = demographics.length === 1 && demographics[0]?.name === t('wizard.defaults.tierLabel');
    if (demographics.length === 0 || hasPolicyOnlyDemographics) {
      setDemographics([
        {
          id: generateId(),
          name: t('wizard.defaults.dimensions.age'),
          categories: [t('wizard.defaults.ageRanges.young'), t('wizard.defaults.ageRanges.middle'), t('wizard.defaults.ageRanges.senior')],
        },
        {
          id: generateId(),
          name: t('wizard.defaults.dimensions.location'),
          categories: [t('wizard.defaults.categories.urban'), t('wizard.defaults.categories.suburban'), t('wizard.defaults.categories.rural')],
        },
      ]);
    }
  }, [showTierControls, demographics, genCount, tierOrder]);

  useEffect(() => {
    if (showTierControls) return;

    if (Object.prototype.hasOwnProperty.call(newAgentType.properties || {}, 'tier')) {
      const nextProperties = { ...(newAgentType.properties || {}) };
      delete nextProperties.tier;
      setNewAgentType((current) => ({
        ...current,
        properties: nextProperties,
      }));
    }

    agentTypes.forEach((agent) => {
      if (!Object.prototype.hasOwnProperty.call(agent.properties || {}, 'tier')) {
        return;
      }
      const nextProperties = { ...(agent.properties || {}) };
      delete nextProperties.tier;
      updateAgentType(agent.id, { properties: nextProperties });
    });
  }, [showTierControls]);

  // Update archetypes when demographics change
  useEffect(() => {
    if (demographics.length > 0 && demographics.every(d => d.categories.length > 0)) {
      setArchetypes(generateArchetypes(demographics));
    } else {
      setArchetypes([]);
    }
  }, [demographics]);

  useEffect(() => {
    setPropertyDrafts((current) => {
      const next: Record<string, Array<{ id: string; originalKey: string; key: string; value: string }>> = {};
      agentTypes.forEach((agent) => {
        const existing = current[agent.id] || [];
        const existingByOriginalKey = new Map(existing.map((item) => [item.originalKey, item]));
        next[agent.id] = Object.entries(agent.properties || {})
          .filter(([key]) => key !== 'avatarUrl')
          .map(([key, value]) => {
            const match = existingByOriginalKey.get(key);
            return {
              id: match?.id || generateId(),
              originalKey: key,
              key: match?.key ?? key,
              value: match?.value ?? String(value ?? ''),
            };
          });
      });
      return next;
    });
  }, [agentTypes]);

  // ==================== Agent Mode Options ====================

  const agentModes = [
    {
      id: 'manual',
      title: t('experimentBuilder.step4.modes.manual.title'),
      description: t('experimentBuilder.step4.modes.manual.description'),
      icon: '✏️',
    },
    {
      id: 'demographic',
      title: t('experimentBuilder.step4.modes.demographic.title'),
      description: t('experimentBuilder.step4.modes.demographic.description'),
      icon: '👥',
    },
    {
      id: 'import',
      title: t('experimentBuilder.step4.modes.import.title'),
      description: t('experimentBuilder.step4.modes.import.description'),
      icon: '📁',
    },
  ];

  // ==================== Manual Mode Handlers ====================

  const handleAddAgentType = () => {
    if (!newAgentType.label.trim()) return;
    const inferredTier = inferOrderedTier(newAgentType, tierOrder);
    const count = Math.max(1, newAgentType.count || 1);
    for (let i = 0; i < count; i++) {
      const nextProperties = { ...(newAgentType.properties || {}) };
      if (showTierControls) {
        nextProperties.tier = inferredTier || String(newAgentType.properties?.tier || '');
      } else {
        delete nextProperties.tier;
      }
      const suffix = count > 1 ? ` ${i + 1}` : '';
      addAgentType({
        ...newAgentType,
        id: `${newAgentType.id || `agent-${Date.now()}`}-${i}`,
        label: `${newAgentType.label}${suffix}`,
        count: 1,
        providerId: selectedProviderId,
        properties: nextProperties,
      });
    }
    setNewAgentType({
      id: '',
      label: '',
      count: 1,
      rolePrompt: '',
      userProfile: '',
      properties: showTierControls ? { tier: '' } : {},
      providerId: selectedProviderId,
    });
  };

  const handleLoadGAWorldPopulation = () => {
    const agentIds = getGAWorldStarterCohortIds(selectedGAWorldPopulation).join(',');
    setIsLoadingGAWorldPopulation(true);
    void loadDefaultAgentsForScenario('gaworld', agentIds)
      .then(() => {
        setImportError(null);
        setIsAgentListOpen(true);
      })
      .catch((error: unknown) => {
        console.error('Failed to load GAWorld starter residents:', error);
        setImportError(`Failed to load GAWorld agents: ${error instanceof Error ? error.message : String(error)}`);
      })
      .finally(() => {
        setIsLoadingGAWorldPopulation(false);
      });
  };

  const handleUpdateTier = (id: string, tier: TierValue) => {
    const current = agentTypes.find((agent) => agent.id === id);
    updateAgentType(id, {
      properties: {
        ...(current?.properties || {}),
        tier,
      },
    });
  };

  const handleTierCountChange = (value: string) => {
    const nextCount = Math.max(2, parseInt(value, 10) || 2);
    setTierOrderDraft((current) => resizeTierOrder(current, nextCount));
  };

  const handleTierNameChange = (index: number, value: string) => {
    setTierOrderDraft((current) => current.map((tier, idx) => (idx === index ? value : tier)));
  };

  const handleApplyTierOrder = () => {
    const nextTierOrder = tierOrderDraft.map((tier) => tier.trim());
    setScenarioParams({
      ...scenarioParams,
      tier_order: nextTierOrder,
    });

    if (showTierControls) {
      const selectedTier = String(newAgentType.properties?.tier || '').trim();
      if (selectedTier && !nextTierOrder.some((tier) => tier.toLowerCase() === selectedTier.toLowerCase())) {
        const nextProperties = { ...(newAgentType.properties || {}) };
        delete nextProperties.tier;
        setNewAgentType((current) => ({ ...current, properties: nextProperties }));
      }

      agentTypes.forEach((agent) => {
        const currentTier = String(agent.properties?.tier || '').trim();
        if (!currentTier) return;
        if (nextTierOrder.some((tier) => tier.toLowerCase() === currentTier.toLowerCase())) return;
        const nextProperties = { ...(agent.properties || {}) };
        delete nextProperties.tier;
        updateAgentType(agent.id, { properties: nextProperties });
      });
    }
  };

  const handleAddProperty = (id: string) => {
    const current = agentTypes.find((agent) => agent.id === id);
    const properties = { ...(current?.properties || {}) };
    let nextKey = 'new_property';
    let idx = 1;
    while (properties[nextKey] !== undefined) {
      idx += 1;
      nextKey = `new_property_${idx}`;
    }
    properties[nextKey] = '';
    updateAgentType(id, { properties });
  };

  const handleDraftPropertyChange = (agentId: string, rowId: string, field: 'key' | 'value', value: string) => {
    setPropertyDrafts((current) => ({
      ...current,
      [agentId]: (current[agentId] || []).map((item) =>
        item.id === rowId ? { ...item, [field]: value } : item
      ),
    }));
  };

  const handleCommitPropertyKey = (agentId: string, rowId: string) => {
    const row = (propertyDrafts[agentId] || []).find((item) => item.id === rowId);
    if (!row) return;

    const oldKey = row.originalKey;
    const newKey = row.key.trim();
    if (!newKey) {
      setPropertyDrafts((current) => ({
        ...current,
        [agentId]: (current[agentId] || []).map((item) =>
          item.id === rowId ? { ...item, key: item.originalKey } : item
        ),
      }));
      return;
    }
    if (newKey === oldKey) return;

    const linkedAgents = agentTypes.filter((agent) => Object.prototype.hasOwnProperty.call(agent.properties || {}, oldKey));
    if (linkedAgents.length > 1) {
      const confirmed = window.confirm(
        t('experimentBuilder.step4.sharedPropertyConfirm', {
          defaultValue: 'This property is shared by multiple agents. Rename it for all linked agents?',
          key: oldKey,
          count: linkedAgents.length,
        })
      );
      if (!confirmed) {
        setPropertyDrafts((current) => ({
          ...current,
          [agentId]: (current[agentId] || []).map((item) =>
            item.id === rowId ? { ...item, key: item.originalKey } : item
          ),
        }));
        return;
      }
    }

    linkedAgents.forEach((agent) => {
      const properties = { ...(agent.properties || {}) };
      const value = properties[oldKey];
      delete properties[oldKey];
      properties[newKey] = value;
      updateAgentType(agent.id, { properties });
    });
  };

  const handleCommitPropertyValue = (agentId: string, rowId: string) => {
    const row = (propertyDrafts[agentId] || []).find((item) => item.id === rowId);
    if (!row) return;
    const effectiveKey = row.key.trim() || row.originalKey;
    const current = agentTypes.find((agent) => agent.id === agentId);
    const properties = { ...(current?.properties || {}) };
    if (effectiveKey !== row.originalKey) {
      delete properties[row.originalKey];
    }
    properties[effectiveKey] = row.value;
    updateAgentType(agentId, { properties });
  };

  const handleRemoveProperty = (id: string, key: string) => {
    const current = agentTypes.find((agent) => agent.id === id);
    const properties = { ...(current?.properties || {}) };
    delete properties[key];
    updateAgentType(id, { properties });
  };

  // ==================== Demographic Mode Handlers ====================

  const handleAddDemographic = () => {
    setDemographics([...demographics, { id: generateId(), name: 'New Dimension', categories: [] }]);
  };

  const handleRemoveDemographic = (id: string) => {
    if (demographics.length > 1) {
      setDemographics(demographics.filter((d) => d.id !== id));
    }
  };

  const handleUpdateDemographicName = (id: string, name: string) => {
    setDemographics(demographics.map((d) => (d.id === id ? { ...d, name } : d)));
  };

  const handleUpdateDemographicCategories = (id: string, categories: string) => {
    const cats = categories.split('\n').map((c) => c.trim()).filter((c) => c);
    setDemographics(demographics.map((d) => (d.id === id ? { ...d, categories: cats } : d)));
  };

  const handleUpdateCategoryName = (demoId: string, catIndex: number, value: string) => {
    setDemographics(
      demographics.map((d) => {
        if (d.id === demoId) {
          const newCats = [...d.categories];
          newCats[catIndex] = value;
          return { ...d, categories: newCats };
        }
        return d;
      })
    );
  };

  const handleAddCategory = (demoId: string) => {
    setDemographics(
      demographics.map((d) => {
        if (d.id === demoId) {
          return { ...d, categories: [...d.categories, 'New Category'] };
        }
        return d;
      })
    );
  };

  const handleRemoveCategory = (demoId: string, catIndex: number) => {
    setDemographics(
      demographics.map((d) => {
        if (d.id === demoId && d.categories.length > 1) {
          return { ...d, categories: d.categories.filter((_, i) => i !== catIndex) };
        }
        return d;
      })
    );
  };

  const handleUpdateArchetypeProbability = (archId: string, newProb: number) => {
    const oldProb = archetypes.find((a) => a.id === archId)?.probability || 0;
    const currentTotal = archetypes.reduce((sum, a) => sum + a.probability, 0);
    const remainingTotal = currentTotal - oldProb;

    setArchetypes(
      archetypes.map((a) => {
        if (a.id === archId) {
          return { ...a, probability: Math.max(0, Math.min(1, newProb)) };
        } else if (remainingTotal > 0) {
          const scale = (1 - newProb) / remainingTotal;
          return { ...a, probability: Math.max(0, a.probability * scale) };
        }
        return a;
      })
    );
  };

  const handleNormalizeProbabilities = () => {
    const total = archetypes.reduce((sum, a) => sum + a.probability, 0) || 1;
    setArchetypes(archetypes.map((a) => ({ ...a, probability: a.probability / total })));
  };

  const handleAddTrait = () => {
    setTraits([...traits, { id: generateId(), name: `Trait ${traits.length + 1}`, mean: 50, std: 15 }]);
  };

  const handleRemoveTrait = (id: string) => {
    if (traits.length > 1) {
      setTraits(traits.filter((t) => t.id !== id));
    }
  };

  const handleUpdateTrait = (id: string, field: keyof TraitConfig, value: string | number) => {
    setTraits(traits.map((t) => (t.id === id ? { ...t, [field]: value } : t)));
  };

  // ==================== LLM Allocation Handlers ====================

  const handleAddLlmAllocation = () => {
    if (llmProviders.length === 0) {
      console.warn('[handleAddLlmAllocation] No LLM providers available');
      return;
    }

    const newCount = llmAllocations.length + 1;
    const basePercentage = Math.floor(100 / newCount);
    const remainder = 100 - (basePercentage * newCount);

    // Add the new allocation first (at base percentage, no remainder)
    const firstProvider = llmProviders[0];
    const withNew = [
      ...llmAllocations,
      {
        providerId: firstProvider.id,
        providerName: firstProvider.name,
        modelName: firstProvider.model || '',
        percentage: basePercentage,
      },
    ];

    // Redistribute evenly — first item absorbs any remainder
    const redistributed = withNew.map((a, i) => ({
      ...a,
      percentage: basePercentage + (i === 0 ? remainder : 0),
    }));

    setLlmAllocations(redistributed);
  };

  const handleRemoveLlmAllocation = (index: number) => {
    const newAllocations = llmAllocations.filter((_, i) => i !== index);

    if (newAllocations.length === 0) {
      setLlmAllocations([]);
      return;
    }

    // Redistribute percentages evenly — first item absorbs any remainder
    const basePercentage = Math.floor(100 / newAllocations.length);
    const remainder = 100 - (basePercentage * newAllocations.length);

    const redistributed = newAllocations.map((a, i) => ({
      ...a,
      percentage: basePercentage + (i === 0 ? remainder : 0),
    }));

    setLlmAllocations(redistributed);
  };

  const handleUpdateLlmAllocation = (index: number, field: keyof LLMAllocation, value: number | string) => {
    setLlmAllocations(llmAllocations.map((a, i) => {
      if (i !== index) return a;
      const updated = { ...a, [field]: value };
      // When provider changes, sync name and model from llmProviders
      if (field === 'providerId') {
        const provider = llmProviders.find((p) => p.id === Number(value));
        if (provider) {
          updated.providerName = provider.name;
          updated.modelName = provider.model || '';
        }
      }
      return updated;
    }));
  };

  const handleGenerateAgents = async () => {
    if (demographics.length === 0 || demographics.some((d) => d.categories.length === 0)) {
      setImportError('Please add at least one demographic dimension with categories.');
      return;
    }

    const totalAllocation = llmAllocations.reduce((sum, item) => sum + item.percentage, 0);
    if (llmAllocations.length > 0 && totalAllocation !== 100) {
      setImportError('LLM distribution must sum to 100%.');
      return;
    }

    setIsGenerating(true);
    setImportError(null);

    try {
      const currentLang = isZh() ? 'zh' : 'en';

      // Build demographics array
      const demographicsData = demographics.map((d) => ({
        name: d.name,
        categories: d.categories,
      }));

      // Build archetype probabilities
      const archetypeProbabilities: Record<string, number> = {};
      archetypes.forEach((a) => {
        archetypeProbabilities[a.id] = a.probability;
      });

      // Build traits data
      const traitsData = traits.map((t) => ({
        name: t.name,
        mean: t.mean,
        std: t.std,
      }));

      // Call the real backend API
      const generated = await generateAgentsWithDemographics(
        genCount,
        demographicsData,
        archetypeProbabilities,
        traitsData,
        currentLang,
        selectedProviderId ?? undefined
      );

      const defaultProvider = llmProviders.find((provider) => provider.id === selectedProviderId) || llmProviders[0];
      const distributedAgents = applyLlmDistribution(
        generated,
        llmAllocations,
        `${scenarioId || 'experiment'}:${selectedProviderId || 'default'}:${genCount}`,
        {
          provider: defaultProvider?.provider || generated[0]?.llmConfig?.provider || 'backend',
          model: defaultProvider?.model || generated[0]?.llmConfig?.model || 'default',
          provider_id: defaultProvider?.id ?? selectedProviderId ?? generated[0]?.provider_id ?? null,
        },
      );

      setGeneratedAgents(distributedAgents);

      // Convert generated agents to ManualAgentType format and add to store
      distributedAgents.forEach((agent) => {
        const inferredTier = inferOrderedTier({
          properties: {
            tier: agent.properties?.tier,
            [TIER_PROPERTY_KEY]: agent.properties?.[TIER_PROPERTY_KEY],
          },
          rolePrompt: agent.profile,
          userProfile: agent.profile,
          label: agent.name,
        }, tierOrder);
        const nextProperties: Record<string, unknown> = {
          avatarUrl: agent.avatarUrl,
          ...agent.properties,
          archetype_id: agent.properties?.archetype_id || '',
          demographic_attributes: JSON.stringify(agent.properties || {}),
        };
        if (showTierControls) {
          nextProperties.tier = inferredTier || String(agent.properties?.tier || agent.properties?.[TIER_PROPERTY_KEY] || '');
        } else {
          delete nextProperties.tier;
        }
        const agentType: ManualAgentType = {
          id: agent.id,
          label: agent.name,
          count: 1,
          rolePrompt: agent.profile,
          userProfile: agent.profile,
          properties: nextProperties,
          providerId: agent.provider_id ?? undefined,
        };
        addAgentType(agentType);
      });
    } catch (error) {
      console.error('Agent generation error:', error);
      setImportError(`Failed to generate agents: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsGenerating(false);
    }
  };

  // ==================== Computed Values ====================

  const totalAgents = agentTypes.reduce((sum, t) => sum + t.count, 0);

  // Virtual list — only renders rows visible in the 500px scroll window.
  // measureElement lets rows grow when expanded without layout thrash.
  const agentVirtualizer = useVirtualizer({
    count: agentTypes.length,
    getScrollElement: () => agentListRef.current,
    estimateSize: () => 49, // compact row height (px) — re-measured automatically
    overscan: 8,
  });
  const tierPreviewStats = useMemo(() => {
    const counts: Record<string, number> = {};
    tierOrder.forEach((tier) => {
      counts[tier] = 0;
    });

    let unassigned = 0;
    agentTypes.forEach((agent) => {
      const amount = Math.max(1, agent.count || 1);
      const matchedTier = inferOrderedTier(agent, tierOrder);
      if (matchedTier) {
        counts[matchedTier] = (counts[matchedTier] || 0) + amount;
        return;
      }
      unassigned += amount;
    });

    return { counts, unassigned };
  }, [agentTypes, tierOrder]);
  const sharedPropertyOwners = useMemo(() => {
    const owners: Record<string, string[]> = {};
    agentTypes.forEach((agent) => {
      Object.keys(agent.properties || {})
        .filter((key) => key !== 'avatarUrl')
        .forEach((key) => {
          if (!owners[key]) {
            owners[key] = [];
          }
          owners[key].push(agent.label);
        });
    });
    return owners;
  }, [agentTypes]);

  // ==================== Render ====================

  return (
    <div className="space-y-6">
      {/* Mode Selection */}
      <div>
        <h3 className="text-lg font-semibold mb-3" style={{ color: 'var(--ss-heading)' }}>
          {t('experimentBuilder.step4.modeTitle')}
        </h3>
        <div className="grid grid-cols-3 gap-4">
          {agentModes.map((mode) => (
            <button
              key={mode.id}
              onClick={() => setAgentMode(mode.id as 'manual' | 'demographic' | 'import')}
              className="p-4 border-2 rounded-lg text-left transition-all"
              style={agentMode === mode.id
                ? { background: 'var(--ss-brand-soft)', borderColor: 'var(--ss-brand-primary)' }
                : { background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }}
            >
              <span className="text-2xl mb-2 block">{mode.icon}</span>
              <h4 className="font-semibold" style={{ color: 'var(--ss-heading)' }}>{mode.title}</h4>
              <p className="text-sm mt-1" style={{ color: 'var(--ss-text-muted)' }}>{mode.description}</p>
            </button>
          ))}
        </div>
      </div>

      {scenarioId === 'gaworld' && agentMode === 'manual' && agentTypes.length === 0 && (
        <GAWorldPopulationChooser
          selectedCount={selectedGAWorldPopulation}
          isLoading={isLoadingGAWorldPopulation}
          onSelectCount={setSelectedGAWorldPopulation}
          onLoadResidents={handleLoadGAWorldPopulation}
        />
      )}

      {showTierControls && (
        <div className="space-y-4">
          <div className="p-4 border rounded-lg" style={{ background: 'var(--ss-accent-warm-soft)', borderColor: 'var(--ss-layer-outline-strong)' }}>
            <h4 className="font-semibold mb-2" style={{ color: 'var(--ss-heading)' }}>{t('experimentBuilder.step4.tierConfigTitle')}</h4>
            <p className="text-sm mb-3" style={{ color: 'var(--ss-text)' }}>
              {t('experimentBuilder.step4.tierConfigDesc')}
            </p>
            <div className="mb-3 grid grid-cols-1 md:grid-cols-[160px_1fr] gap-3 items-end">
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step4.tierCountLabel')}</label>
                <input
                  type="number"
                  min="2"
                  value={tierOrderDraft.length}
                  onChange={(e) => handleTierCountChange(e.target.value)}
                  className="w-full px-3 py-2 text-sm border rounded"
                  style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                />
              </div>
              <div className="text-xs" style={{ color: 'var(--ss-text-muted)' }}>
                {t('experimentBuilder.step4.tierConfigHint')}
              </div>
            </div>
            <div className="space-y-2">
              {tierOrderDraft.map((tierName, index) => (
                <div key={index} className="grid grid-cols-[96px_1fr] gap-3 items-center">
                  <div className="text-sm font-medium" style={{ color: 'var(--ss-text)' }}>
                    {t('experimentBuilder.step4.tierLevelLabel', { index: index + 1 })}
                  </div>
                  <input
                    type="text"
                    value={tierName}
                    onChange={(e) => handleTierNameChange(index, e.target.value)}
                    className="w-full px-3 py-2 text-sm border rounded"
                    style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                    placeholder={t('experimentBuilder.step4.tierNamePlaceholder', { name: defaultTierName(index) })}
                  />
                </div>
              ))}
            </div>
            {!tierOrderDraftValid && (
              <div className="mt-3 text-xs" style={{ color: 'var(--ss-danger)' }}>{t('experimentBuilder.step4.tierDraftInvalid')}</div>
            )}
            <div className="mt-3">
              <Button size="sm" onClick={handleApplyTierOrder} disabled={!tierOrderDraftValid}>
                {t('experimentBuilder.step4.applyTierConfig')}
              </Button>
            </div>
          </div>

          <div className="p-4 border rounded-lg" style={{ background: 'var(--ss-secondary-soft)', borderColor: 'var(--ss-secondary)' }}>
            <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
              <div>
                <h4 className="font-semibold" style={{ color: 'var(--ss-heading)' }}>{t('experimentBuilder.step4.tierPreviewTitle')}</h4>
                <p className="text-sm mt-1" style={{ color: 'var(--ss-text)' }}>
                  {t('experimentBuilder.step4.tierPreviewDesc', { count: tierOrder.length })}
                </p>
              </div>
              <span
                className="rounded-full px-3 py-1 text-xs font-medium"
                style={{
                  background: 'var(--ss-page-surface)',
                  color: 'var(--ss-text)',
                  border: '1px solid var(--ss-border)',
                }}
              >
                {t(`experimentBuilder.step4.cascadeModeLabels.${cascadeMode}`)}
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-2 mb-4">
              {tierOrder.map((tier, index) => (
                <React.Fragment key={tier}>
                  <div className="rounded-lg border px-3 py-2 text-sm shadow-sm" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-secondary)', color: 'var(--ss-text)' }}>
                    <div className="text-[11px] font-medium uppercase tracking-wide" style={{ color: 'var(--ss-info)' }}>
                      {t('experimentBuilder.step4.tierLevelLabel', { index: index + 1 })}
                    </div>
                    <div className="font-medium">{tier}</div>
                  </div>
                  {index < tierOrder.length - 1 && (
                    <span className="text-lg leading-none" style={{ color: 'var(--ss-info)' }}>→</span>
                  )}
                </React.Fragment>
              ))}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
              {tierOrder.map((tier, index) => (
                <div key={`${tier}-count`} className="rounded-lg border px-3 py-3" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }}>
                  <div className="text-xs font-medium mb-1" style={{ color: 'var(--ss-info)' }}>
                    {t('experimentBuilder.step4.tierLevelLabel', { index: index + 1 })}
                  </div>
                  <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>{tier}</div>
                  <div className="text-xs mt-1" style={{ color: 'var(--ss-text-muted)' }}>
                    {t('experimentBuilder.step4.tierAssignedCount', { count: tierPreviewStats.counts[tier] || 0 })}
                  </div>
                </div>
              ))}
              <div className="rounded-lg border border-dashed px-3 py-3" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}>
                <div className="text-xs font-medium mb-1" style={{ color: 'var(--ss-info)' }}>
                  {t('experimentBuilder.step4.unassignedTitle')}
                </div>
                <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                  {t('experimentBuilder.step4.unassignedCount', { count: tierPreviewStats.unassigned })}
                </div>
                <div className="text-xs mt-1" style={{ color: 'var(--ss-text-muted)' }}>
                  {t('experimentBuilder.step4.unassignedHint')}
                </div>
              </div>
            </div>

            {hasPendingTierDraft && (
              <div
                className="mt-3 rounded-md border px-3 py-2 text-xs"
                style={{ background: 'var(--ss-brand-soft)', borderColor: 'var(--ss-brand-primary)', color: 'var(--ss-brand-on)' }}
              >
                {t('experimentBuilder.step4.tierDraftPending')}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Manual Agent Types */}
      {agentMode === 'manual' && (
        <div className="p-4 border rounded-lg" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }}>
          <h4 className="font-semibold mb-3" style={{ color: 'var(--ss-heading)' }}>{t('experimentBuilder.step4.defineTypes')}</h4>
          <div className="mb-4 rounded-lg border px-4 py-3 text-sm" style={{ background: 'var(--ss-brand-soft)', borderColor: 'var(--ss-brand-primary)', color: 'var(--ss-text)' }}>
            {t('experimentBuilder.step4.manualHint')}
          </div>

          {/* Add New Agent Type */}
          <div className="mb-4 p-3 rounded-md" style={{ background: 'var(--ss-page-surface-muted)' }}>
            <div className="grid grid-cols-2 gap-3 mb-3">
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step4.typeLabel')}</label>
                <input
                  type="text"
                  value={newAgentType.label}
                  onChange={(e) => setNewAgentType({ ...newAgentType, label: e.target.value })}
                  placeholder={t('experimentBuilder.step4.typeLabelPlaceholder')}
                  className="w-full px-2 py-1.5 text-sm border rounded"
                  style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                />
              </div>
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step4.count')}</label>
                <input
                  type="number"
                  min="1"
                  value={newAgentType.count}
                  onChange={(e) =>
                    setNewAgentType({ ...newAgentType, count: parseInt(e.target.value) || 1 })
                  }
                  className="w-full px-2 py-1.5 text-sm border rounded"
                  style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 mb-3">
              {showTierControls && (
                <div>
                  <label className="block text-xs font-medium mb-1" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step4.tier')}</label>
                  <select
                    value={String(newAgentType.properties?.tier || '')}
                    onChange={(e) => setNewAgentType({
                      ...newAgentType,
                      properties: { ...newAgentType.properties, tier: e.target.value },
                    })}
                    className="w-full px-2 py-1.5 text-sm border rounded"
                    style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                  >
                    <option value="">{t('experimentBuilder.step4.autoDetectTier')}</option>
                      {tierOrder.map((tier) => (
                        <option key={tier} value={tier}>{tier}</option>
                      ))}
                  </select>
                </div>
              )}
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step4.userProfile')}</label>
                <input
                  type="text"
                  value={newAgentType.userProfile}
                  onChange={(e) => setNewAgentType({ ...newAgentType, userProfile: e.target.value })}
                  placeholder={t('experimentBuilder.step4.userProfilePlaceholder')}
                  className="w-full px-2 py-1.5 text-sm border rounded"
                  style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                />
              </div>
            </div>
            <div className="mb-3">
              <label className="block text-xs font-medium mb-1" style={{ color: 'var(--ss-text)' }}>
                {t('experimentBuilder.step4.rolePrompt')}
              </label>
              <textarea
                value={newAgentType.rolePrompt}
                onChange={(e) => setNewAgentType({ ...newAgentType, rolePrompt: e.target.value })}
                placeholder={t('experimentBuilder.step4.rolePromptPlaceholder')}
                className="w-full px-2 py-1.5 text-sm border rounded"
                style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                rows={2}
              />
            </div>
            <Button onClick={handleAddAgentType} size="sm" disabled={!newAgentType.label.trim()}>
              {t('experimentBuilder.step4.addAgentType')}
            </Button>
          </div>
        </div>
      )}

      {/* Demographic Generation */}
      {agentMode === 'demographic' && (
        <div className="p-4 border rounded-lg" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }}>
          {/* Agent Generation LLM Selector */}
          {llmProviders.length > 0 && (
            <div className="mb-4 p-3 rounded-lg" style={{ background: 'var(--ss-page-surface-muted)' }}>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step4.generationLlmProvider')}</label>
              <p className="text-xs mb-2" style={{ color: 'var(--ss-text-subtle)' }}>{t('experimentBuilder.step4.generationLlmProviderHint')}</p>
              <select
                value={selectedProviderId || ''}
                onChange={(e) => setSelectedProviderId(e.target.value ? Number(e.target.value) : null)}
                className="w-full px-3 py-2 border rounded-lg"
                style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
              >
                <option value="">{t('experimentBuilder.step4.defaultProvider')}</option>
                {llmProviders.map((p: LLMProvider) => (
                  <option key={p.id} value={p.id}>
                    {p.name} {p.model ? ` (${p.model})` : ''}
                    {p.is_active && <span className="ml-1" style={{ color: 'var(--ss-success)' }}>● Active</span>}
                    {p.is_default && <span className="ml-1" style={{ color: 'var(--ss-info)' }}>● Default</span>}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Use the flexible demographic editor */}
          <Step2DemographicsEditor
            demographics={demographics}
            archetypes={archetypes}
            traits={traits}
            genCount={genCount}
            isGenerating={isGenerating}
            onAddDemographic={handleAddDemographic}
            onRemoveDemographic={handleRemoveDemographic}
            onUpdateDemographicName={handleUpdateDemographicName}
            onUpdateDemographicCategories={handleUpdateDemographicCategories}
            onUpdateCategoryName={handleUpdateCategoryName}
            onAddCategory={handleAddCategory}
            onRemoveCategory={handleRemoveCategory}
            onUpdateArchetypeProbability={handleUpdateArchetypeProbability}
            onNormalizeProbabilities={handleNormalizeProbabilities}
            onAddTrait={handleAddTrait}
            onRemoveTrait={handleRemoveTrait}
            onUpdateTrait={handleUpdateTrait}
            onSetGenCount={setGenCount}
            onGenerateAgents={handleGenerateAgents}
            customAgents={generatedAgents}
            setCustomAgents={setGeneratedAgents}
            importError={importError}
            llmAllocations={llmAllocations}
            onAddLlmAllocation={handleAddLlmAllocation}
            onRemoveLlmAllocation={handleRemoveLlmAllocation}
            onUpdateLlmAllocation={handleUpdateLlmAllocation}
            availableProviders={llmProviders as any}
            providersLoading={false}
            useTranslation={true}
            t={t}
          />
        </div>
      )}

      {/* Editable Agent List */}
      <div className="border rounded-lg overflow-hidden" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }}>
        {/* Collapsible header */}
        <button
          type="button"
          onClick={() => setIsAgentListOpen((o) => !o)}
          className="w-full flex items-center justify-between px-4 py-3 transition-colors text-left"
          style={{ color: 'var(--ss-heading)' }}
        >
          <div className="flex items-center gap-2">
            <h4 className="font-semibold">{t('experimentBuilder.step4.agentListTitle')}</h4>
            <span className="text-sm" style={{ color: 'var(--ss-text-subtle)' }}>
              ({t('experimentBuilder.step4.totalAgents', { count: totalAgents })})
            </span>
          </div>
          <ChevronDown
            size={18}
            className={`transition-transform duration-200 ${isAgentListOpen ? 'rotate-180' : ''}`}
            style={{ color: 'var(--ss-text-subtle)' }}
          />
        </button>

        {isAgentListOpen && (
          <div style={{ borderTop: '1px solid var(--ss-border)' }}>
            {agentTypes.length === 0 ? (
              <p className="text-sm text-center py-4" style={{ color: 'var(--ss-text-muted)' }}>{t('experimentBuilder.step4.noTypes')}</p>
            ) : (
              /* Scroll container — fixed height so the virtualizer knows its viewport */
              <div
                ref={agentListRef}
                className="overflow-y-auto"
                style={{ height: '500px' }}
              >
                {/* Inner div height = sum of all row heights, real and virtual */}
                <div
                  className="relative w-full"
                  style={{ height: `${agentVirtualizer.getTotalSize()}px` }}
                >
                  {agentVirtualizer.getVirtualItems().map((virtualRow) => {
                  const type = agentTypes[virtualRow.index];
                  const avatarUrl = type.properties?.avatarUrl as string ||
                    `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(type.label)}`;
                  const tier = inferOrderedTier(type, tierOrder);
                  const editableProperties = propertyDrafts[type.id] || [];
                  const isExpanded = expandedAgentId === type.id;
                  const assignedProvider = type.providerId
                    ? llmProviders.find((p) => p.id === type.providerId)
                    : null;

                  return (
                    // Absolutely positioned wrapper required by the virtualizer.
                    // data-index + ref={measureElement} lets it track dynamic row heights.
                    <div
                      key={virtualRow.key}
                      data-index={virtualRow.index}
                      ref={agentVirtualizer.measureElement}
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        transform: `translateY(${virtualRow.start}px)`,
                        padding: '2px 8px',
                      }}
                    >
                      <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--ss-border)' }}>
                      {/* Compact row — always visible */}
                      <div
                        className="flex items-center gap-3 px-3 py-2 cursor-pointer transition-colors"
                        style={{ background: 'var(--ss-page-surface)' }}
                        onClick={() => setExpandedAgentId(isExpanded ? null : type.id)}
                      >
                        <img
                          src={avatarUrl}
                          alt={type.label}
                          className="w-8 h-8 rounded-full border flex-shrink-0"
                          style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface-muted)' }}
                        />
                        <span className="flex-1 text-sm font-medium truncate" style={{ color: 'var(--ss-heading)' }}>{type.label}</span>
                        {assignedProvider && (
                          <span className="text-xs px-2 py-0.5 rounded-full flex-shrink-0" style={{ background: 'var(--ss-accent-warm-soft)', color: 'var(--ss-text)' }}>
                            {assignedProvider.name}
                          </span>
                        )}
                        {showTierControls && tier && (
                          <span className="text-xs px-2 py-0.5 rounded-full flex-shrink-0" style={{ background: 'var(--ss-surface-strong)', color: 'var(--ss-text-muted)' }}>
                            {tier}
                          </span>
                        )}
                        <ChevronDown
                          size={14}
                          className={`flex-shrink-0 transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
                          style={{ color: 'var(--ss-text-subtle)' }}
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => { e.stopPropagation(); removeAgentType(type.id); }}
                          className="flex-shrink-0 px-2"
                          style={{ color: 'var(--ss-danger)' }}
                        >
                          {t('experimentBuilder.step4.remove')}
                        </Button>
                      </div>

                      {/* Expanded edit form */}
                      {isExpanded && (
                        <div className="p-4" style={{ borderTop: '1px solid var(--ss-border)' }}>
                          <div className="mb-4 flex items-start gap-3">
                            <img
                              src={avatarUrl}
                              alt={type.label}
                              className="w-12 h-12 rounded-full border"
                              style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface-muted)' }}
                            />
                            <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-3">
                              <div>
                                <label className="block text-xs font-medium mb-1" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step4.agentName')}</label>
                                <input
                                  type="text"
                                  value={type.label}
                                  onChange={(e) => updateAgentType(type.id, { label: e.target.value })}
                                  className="w-full px-3 py-2 text-sm border rounded"
                                  style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                                />
                              </div>
                              {showTierControls && (
                                <div>
                                  <label className="block text-xs font-medium mb-1" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step4.tier')}</label>
                                  <select
                                    value={tier}
                                    onChange={(e) => handleUpdateTier(type.id, e.target.value as TierValue)}
                                    className="w-full px-3 py-2 text-sm border rounded"
                                    style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                                  >
                                    <option value="">{t('experimentBuilder.step4.autoDetectTier')}</option>
                                    {tierOrder.map((tierOption) => (
                                      <option key={tierOption} value={tierOption}>{tierOption}</option>
                                    ))}
                                  </select>
                                </div>
                              )}
                              <div className="md:col-span-2">
                                <label className="block text-xs font-medium mb-1" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step4.userProfile')}</label>
                                <input
                                  type="text"
                                  value={type.userProfile || ''}
                                  onChange={(e) => updateAgentType(type.id, { userProfile: e.target.value })}
                                  className="w-full px-3 py-2 text-sm border rounded"
                                  style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                                />
                              </div>
                              <div className="md:col-span-2">
                                <label className="block text-xs font-medium mb-1" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step4.rolePrompt')}</label>
                                <textarea
                                  value={type.rolePrompt || ''}
                                  onChange={(e) => updateAgentType(type.id, { rolePrompt: e.target.value })}
                                  rows={3}
                                  className="w-full px-3 py-2 text-sm border rounded"
                                  style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                                />
                              </div>
                              <div>
                                <label className="block text-xs font-medium mb-1" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step4.llmProvider')}</label>
                                <select
                                  value={type.providerId ?? ''}
                                  onChange={(e) => updateAgentType(type.id, { providerId: e.target.value ? Number(e.target.value) : null })}
                                  className="w-full px-3 py-2 text-sm border rounded"
                                  style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                                >
                                  <option value="">{t('experimentBuilder.step4.defaultProvider')}</option>
                                  {llmProviders.map((p) => (
                                    <option key={p.id} value={p.id}>{p.name}{p.model ? ` (${p.model})` : ''}</option>
                                  ))}
                                </select>
                              </div>
                            </div>
                          </div>

                          <div className="rounded-md p-3" style={{ background: 'var(--ss-page-surface-muted)' }}>
                            <div className="mb-3 flex items-center justify-between">
                              <div className="text-xs font-medium" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step4.properties')}</div>
                              <Button size="sm" variant="outline" onClick={() => handleAddProperty(type.id)}>
                                {t('experimentBuilder.step4.addProperty')}
                              </Button>
                            </div>

                            <div className="space-y-2">
                              {editableProperties.length === 0 && (
                                <div className="text-xs" style={{ color: 'var(--ss-text-subtle)' }}>{t('experimentBuilder.step4.noProperties')}</div>
                              )}
                              {editableProperties.map((item) => (
                                <div key={item.id} className="grid grid-cols-[1fr_1fr_auto] gap-2">
                                  <div className="relative">
                                    <input
                                      type="text"
                                      value={item.key}
                                      onChange={(e) => handleDraftPropertyChange(type.id, item.id, 'key', e.target.value)}
                                      onBlur={() => handleCommitPropertyKey(type.id, item.id)}
                                      className="w-full px-2 py-1.5 pr-14 text-sm border rounded"
                                      style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                                    />
                                        {(sharedPropertyOwners[item.originalKey] || []).length > 1 && (
                                          <span
                                            title={t('experimentBuilder.step4.sharedPropertyTooltip', {
                                              key: item.originalKey,
                                              agents: sharedPropertyOwners[item.originalKey].join('、'),
                                            })}
                                            className="absolute right-2 top-1/2 -translate-y-1/2 rounded px-1.5 py-0.5 text-[10px] font-medium cursor-help"
                                            style={{ background: 'var(--ss-brand-soft)', color: 'var(--ss-brand-on)' }}
                                          >
                                            {t('experimentBuilder.step4.sharedPropertyBadge')}
                                          </span>
                                        )}
                                      </div>
                                      <input
                                        type="text"
                                        value={item.value}
                                        onChange={(e) => handleDraftPropertyChange(type.id, item.id, 'value', e.target.value)}
                                        onBlur={() => handleCommitPropertyValue(type.id, item.id)}
                                        className="px-2 py-1.5 text-sm border rounded"
                                        style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border-strong)' }}
                                      />
                                      <Button variant="ghost" size="sm" onClick={() => handleRemoveProperty(type.id, item.originalKey)} style={{ color: 'var(--ss-danger)' }}>
                                        {t('experimentBuilder.step4.remove')}
                                      </Button>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

      {/* File Import */}
      {agentMode === 'import' && (
        <div className="p-4 border rounded-lg" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }}>
          <h4 className="font-semibold mb-3" style={{ color: 'var(--ss-heading)' }}>{t('experimentBuilder.step4.importTitle')}</h4>
          <p className="text-sm mb-3" style={{ color: 'var(--ss-text-muted)' }}>
            {t('experimentBuilder.step4.importDesc')}
          </p>

          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-text)' }}>{t('experimentBuilder.step4.csvFormat')}</label>
              <pre className="text-xs p-2 rounded overflow-x-auto" style={{ background: 'var(--ss-surface-strong)' }}>
                <code>name,role_prompt,user_profile,opinion</code>
              </pre>
            </div>

            <div className="flex gap-2">
              <label className="inline-flex">
                <Button variant="outline" type="button">
                  {t('experimentBuilder.step4.uploadCSV')}
                </Button>
                <input type="file" accept=".csv,.json" className="hidden" />
              </label>
              <label className="inline-flex">
                <Button variant="outline" type="button">
                  {t('experimentBuilder.step4.uploadJSON')}
                </Button>
                <input type="file" accept=".csv,.json" className="hidden" />
              </label>
            </div>

            <div className="p-3 rounded border" style={{ background: 'var(--ss-accent-warm-soft)', borderColor: 'var(--ss-layer-outline-strong)' }}>
              <p className="text-sm" style={{ color: 'var(--ss-text)' }}>ℹ️ {t('experimentBuilder.step4.importInfo')}</p>
            </div>
          </div>
        </div>
      )}

      {/* Total Agents Summary (shown for all modes) */}
      {totalAgents > 0 && (
        <div className="mt-4 p-3 rounded-lg border" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-success)' }}>
          <div className="flex items-center gap-2">
            <span style={{ color: 'var(--ss-success)' }}>✓</span>
            <span className="text-sm" style={{ color: 'var(--ss-success)' }}>
              {t('experimentBuilder.step4.agentsDefined', { count: totalAgents })}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
