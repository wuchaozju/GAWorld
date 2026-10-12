/**
 * Step 5: Network Configuration
 *
 * Configure social network connections between agents.
 * Reuses the network visualization from NetworkEditorModal but embedded in the wizard.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useExperimentBuilder } from '../../store/experiment-builder';
import { Button } from '../ui/button';
import NetworkGraph from '../NetworkGraph';
import {
  RefreshCw,
  Share2,
  Grid3X3,
  Users,
  Shuffle,
  Layers,
  Settings2,
  ChevronRight,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { Agent } from '../../types';

// =============================================================================
// Types
// =============================================================================

type PresetType = 'full' | 'random' | 'ring' | 'star' | 'newman-watts' | 'core-periphery' | 'holme-kim' | 'waxman' | 'sbm';

interface PresetParams {
  random: { connectionChance: number };
  ring: {};
  star: {};
  'newman-watts': { neighborsEachSide: number; shortcutChance: number };
  'core-periphery': {
    influencerPercent: number;
    influencerConnectivity: number;
    influencerReach: number;
    regularConnectivity: number;
  };
  'holme-kim': { newConnections: number; clusteringChance: number };
  waxman: { maxDistance: number; distanceEffect: number };
  sbm: { groupSize: number; withinGroupConnectivity: number; bridgeConnections: number };
}

// =============================================================================
// Preset Definitions
// =============================================================================

// Note: Preset names/descriptions are now translated in the component
// This object only maps preset types to their icons and translation keys
const presetIcons: Record<PresetType, { icon: React.ElementType; translationKey: string }> = {
  full: { icon: Share2, translationKey: 'fully_connected' },
  random: { icon: Shuffle, translationKey: 'random' },
  ring: { icon: RefreshCw, translationKey: 'ring' },
  star: { icon: Users, translationKey: 'star' },
  'newman-watts': { icon: Grid3X3, translationKey: 'small_world' },
  'core-periphery': { icon: Layers, translationKey: 'core_periphery' },
  'holme-kim': { icon: Share2, translationKey: 'scale_free' },
  waxman: { icon: Grid3X3, translationKey: 'spatial' },
  sbm: { icon: Users, translationKey: 'communities' },
};

const defaultParams: PresetParams = {
  random: { connectionChance: 0.3 },
  ring: {},
  star: {},
  'newman-watts': { neighborsEachSide: 2, shortcutChance: 0.1 },
  'core-periphery': {
    influencerPercent: 0.2,
    influencerConnectivity: 0.8,
    influencerReach: 0.4,
    regularConnectivity: 0.1,
  },
  'holme-kim': { newConnections: 3, clusteringChance: 0.5 },
  waxman: { maxDistance: 0.5, distanceEffect: 0.5 },
  sbm: { groupSize: 5, withinGroupConnectivity: 0.6, bridgeConnections: 1 },
};

/**
 * Ensures no agent is isolated (has zero connections).
 * For any isolated agent, creates a connection to a random other agent.
 */
const ensureNoIsolatedNodes = (
  network: Record<string, string[]>,
  ids: string[]
): Record<string, string[]> => {
  if (ids.length <= 1) return network; // Single agent can't have connections

  const result = JSON.parse(JSON.stringify(network));

  for (const agentId of ids) {
    const connections = result[agentId] || [];
    if (connections.length === 0) {
      // Connect to a random other agent
      const others = ids.filter(id => id !== agentId);
      const neighbor = others[Math.floor(Math.random() * others.length)];

      result[agentId] = [neighbor];
      // Ensure reciprocal connection
      if (!result[neighbor].includes(agentId)) {
        result[neighbor] = [...(result[neighbor] || []), agentId];
      }
    }
  }

  return result;
};

// =============================================================================
// ParamSlider Component
// =============================================================================

interface ParamSliderProps {
  labelKey: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  isInteger?: boolean;
}

const ParamSlider: React.FC<ParamSliderProps> = ({
  labelKey,
  value,
  min,
  max,
  step,
  onChange,
  isInteger = false,
}) => {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between">
      <label className="text-[11px] flex-1" style={{ color: 'var(--ss-text-muted)' }}>
        {t(`components.networkEditorModal.${labelKey}`)}
      </label>
      <div className="flex items-center gap-2">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(isInteger ? parseInt(e.target.value) : parseFloat(e.target.value))}
          className="w-20 h-1 accent-brand-500"
        />
        <span className="text-[10px] w-8 text-right" style={{ color: 'var(--ss-text-subtle)' }}>
          {isInteger ? value : value.toFixed(2)}
        </span>
      </div>
    </div>
  );
};

// =============================================================================
// Step5Network Component
// =============================================================================

export const Step5Network: React.FC = () => {
  const { t } = useTranslation();
  const { socialNetwork, setSocialNetwork, agentTypes } = useExperimentBuilder();
  const [linkFrom, setLinkFrom] = useState('');
  const [linkTo, setLinkTo] = useState('');

  // Local state
  const [selectedPreset, setSelectedPreset] = useState<PresetType | null>(null);
  const [params, setParams] = useState<PresetParams>(JSON.parse(JSON.stringify(defaultParams)));

  // Get agent IDs from agent types
  const { agentIds, profileMap } = useMemo(() => {
    const ids: string[] = [];
    const profiles: Record<string, string> = {};
    for (const type of agentTypes) {
      const count = type.count || 1;
      for (let i = 0; i < count; i++) {
        const suffix = count > 1 ? ` ${i + 1}` : '';
        const name = `${type.label}${suffix}`;
        ids.push(name);
        const summary = type.userProfile || type.rolePrompt || '';
        profiles[name] = summary;
      }
    }
    return { agentIds: ids, profileMap: profiles };
  }, [agentTypes]);

  // Map experiment agent data to Agent objects for NetworkGraph.
  // NetworkGraph uses agent.name for node labels and lookup.
  const agents: Agent[] = useMemo(
    () =>
      agentIds.map((name, idx) => ({
        id: String(idx),
        name,
        role: '',
        avatarUrl: '',
        profile: profileMap[name] ?? '',
        llmConfig: { provider: '', model: '' },
        properties: {},
        history: {},
        memory: [],
        knowledgeBase: [],
      })),
    [agentIds, profileMap],
  );

  // Keep manual link selectors in sync with current agents
  useEffect(() => {
    if (agentIds.length === 0) return;
    if (!agentIds.includes(linkFrom)) {
      setLinkFrom(agentIds[0]);
    }
    if (!agentIds.includes(linkTo)) {
      setLinkTo(agentIds[Math.min(1, agentIds.length - 1)]);
    }
  }, [agentIds, linkFrom, linkTo]);

  const edges = useMemo(() => {
    const list: { key: string; source: string; target: string }[] = [];
    const dedup = new Set<string>();
    for (const [source, targets] of Object.entries(socialNetwork)) {
      for (const target of targets) {
        if (!agentIds.includes(source) || !agentIds.includes(target)) continue;
        const key = source < target ? `${source}|${target}` : `${target}|${source}`;
        if (dedup.has(key)) continue;
        dedup.add(key);
        list.push({ key, source, target });
      }
    }
    return list;
  }, [agentIds, socialNetwork]);

  const addLink = () => {
    if (!linkFrom || !linkTo || linkFrom === linkTo) return;
    const key = linkFrom < linkTo ? `${linkFrom}|${linkTo}` : `${linkTo}|${linkFrom}`;
    const alreadyExists = edges.some((edge) => edge.key === key);
    if (alreadyExists) return;

    const next: Record<string, string[]> = {};
    for (const id of agentIds) {
      next[id] = [...(socialNetwork[id] || [])];
    }

    next[linkFrom] = [...(next[linkFrom] || []), linkTo];
    next[linkTo] = [...(next[linkTo] || []), linkFrom];
    setSocialNetwork(next);
  };

  const removeLink = (key: string) => {
    const [a, b] = key.split('|');
    const next: Record<string, string[]> = {};
    for (const id of agentIds) {
      next[id] = (socialNetwork[id] || []).filter((target) => target !== a && target !== b);
    }
    setSocialNetwork(next);
  };

  // Reset params when preset changes
  const resetParams = useCallback((presetKey: keyof PresetParams) => {
    setParams((prev) => ({
      ...prev,
      [presetKey]: { ...defaultParams[presetKey] },
    }));
  }, []);

  // Update param
  const updateParam = useCallback(<K extends keyof PresetParams, P extends keyof PresetParams[K]>(
    preset: K,
    param: P,
    value: PresetParams[K][P]
  ) => {
    setParams((prev) => ({
      ...prev,
      [preset]: { ...prev[preset], [param]: value },
    }));
  }, []);

  // Apply preset
  const applyPreset = useCallback((type: PresetType) => {
    const n = agentIds.length;
    const newNetwork: Record<string, string[]> = {};

    // Initialize empty adjacency list
    agentIds.forEach((id) => {
      newNetwork[id] = [];
    });

    if (type === 'full') {
      // Fully connected
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          newNetwork[agentIds[i]].push(agentIds[j]);
          newNetwork[agentIds[j]].push(agentIds[i]);
        }
      }
    } else if (type === 'ring') {
      // Ring network
      for (let i = 0; i < n; i++) {
        const next = (i + 1) % n;
        newNetwork[agentIds[i]].push(agentIds[next]);
        newNetwork[agentIds[next]].push(agentIds[i]);
      }
    } else if (type === 'star') {
      // Star network (first agent is center)
      if (n > 1) {
        for (let i = 1; i < n; i++) {
          newNetwork[agentIds[0]].push(agentIds[i]);
          newNetwork[agentIds[i]].push(agentIds[0]);
        }
      }
    } else if (type === 'random') {
      const { connectionChance } = params.random;
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          if (Math.random() < connectionChance) {
            newNetwork[agentIds[i]].push(agentIds[j]);
            newNetwork[agentIds[j]].push(agentIds[i]);
          }
        }
      }
    } else if (type === 'newman-watts') {
      const { neighborsEachSide, shortcutChance } = params['newman-watts'];
      const k = Math.min(neighborsEachSide, Math.floor((n - 1) / 2));

      // Ring lattice
      for (let i = 0; i < n; i++) {
        for (let offset = 1; offset <= k; offset++) {
          const neighborIdx = (i + offset) % n;
          const neighborIdx2 = (i - offset + n) % n;
          newNetwork[agentIds[i]].push(agentIds[neighborIdx]);
          newNetwork[agentIds[neighborIdx]].push(agentIds[i]);
        }
      }

      // Shortcuts
      for (let i = 0; i < n; i++) {
        for (let offset = k + 1; offset <= Math.floor(n / 2); offset++) {
          if (Math.random() < shortcutChance) {
            const neighborIdx = (i + offset) % n;
            if (!newNetwork[agentIds[i]].includes(agentIds[neighborIdx])) {
              newNetwork[agentIds[i]].push(agentIds[neighborIdx]);
              newNetwork[agentIds[neighborIdx]].push(agentIds[i]);
            }
          }
        }
      }
    }

    // Ensure no isolated nodes
    const connectedNetwork = ensureNoIsolatedNodes(newNetwork, agentIds);
    setSocialNetwork(connectedNetwork);
  }, [agentIds, params, setSocialNetwork]);

  // Auto-initialize network when agents exist but network is empty
  useEffect(() => {
    if (agentIds.length > 0 && Object.keys(socialNetwork).length === 0) {
      applyPreset('full');
      setSelectedPreset('full');
    }
  }, [agentIds.length, socialNetwork, applyPreset]);


  // Render parameter controls
  const renderParamControls = () => {
    if (!selectedPreset || selectedPreset === 'full' || selectedPreset === 'ring' || selectedPreset === 'star') return null;

    const presetKey = selectedPreset as keyof PresetParams;

    return (
      <div className="space-y-3 p-3 rounded-lg border shadow-sm" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }}>
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold flex items-center gap-1.5" style={{ color: 'var(--ss-text)' }}>
            <Settings2 size={12} />
            {t('components.networkEditorModal.parameterSettings')}
          </span>
          <button
            onClick={() => resetParams(presetKey)}
            className="text-[10px] text-brand-600 hover:text-brand-700 flex items-center gap-0.5"
          >
            <RefreshCw size={10} />
            {t('components.networkEditorModal.resetDefaults')}
          </button>
        </div>

        {selectedPreset === 'random' && (
          <ParamSlider
            labelKey="probabilityAnyTwoConnect"
            value={params.random.connectionChance}
            min={0}
            max={1}
            step={0.05}
            onChange={(v) => updateParam('random', 'connectionChance', v)}
          />
        )}

        {selectedPreset === 'newman-watts' && (
          <div className="space-y-3">
            <ParamSlider
              labelKey="neighborsEachSide"
              value={params['newman-watts'].neighborsEachSide}
              min={1}
              max={5}
              step={1}
              onChange={(v) => updateParam('newman-watts', 'neighborsEachSide', v)}
              isInteger
            />
            <ParamSlider
              labelKey="probabilityLongRangeShortcut"
              value={params['newman-watts'].shortcutChance}
              min={0}
              max={0.5}
              step={0.01}
              onChange={(v) => updateParam('newman-watts', 'shortcutChance', v)}
            />
          </div>
        )}

        {/* Apply Changes Button */}
        <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--ss-border)' }}>
          <button
            onClick={() => {
              if (selectedPreset) {
                applyPreset(selectedPreset);
              }
            }}
            disabled={!selectedPreset}
            className="w-full py-1.5 px-3 bg-brand-500 text-white rounded text-xs font-medium hover:bg-brand-600 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {t('experimentBuilder.step5.applyChanges')}
          </button>
        </div>
      </div>
    );
  };

  // Check if agents are configured
  if (agentTypes.length === 0 || agentIds.length === 0) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="text-center max-w-md">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full mb-4" style={{ background: 'var(--ss-brand-soft)' }}>
            <Users className="w-8 h-8" style={{ color: 'var(--ss-warning)' }} />
          </div>
          <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.step5.noAgentsConfigured')}
          </h3>
          <p style={{ color: 'var(--ss-text-muted)' }}>
            {t('experimentBuilder.step5.goBackToStep4')}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col lg:flex-row gap-0 h-full min-h-[500px]">
      {/* Sidebar Tools */}
      <div className="w-full lg:w-80 shrink-0 border-r p-4 space-y-4 overflow-y-auto" style={{ background: 'var(--ss-page-surface-muted)' }}>
        <div>
          <label className="text-xs font-bold uppercase tracking-wide" style={{ color: 'var(--ss-text-muted)' }}>
            {t('experimentBuilder.step5.networkPresets')}
          </label>
          <p className="text-[10px] mt-0.5 mb-3" style={{ color: 'var(--ss-text-subtle)' }}>
            {t('experimentBuilder.step5.chooseTopology')}
          </p>

          {/* Preset Selection Grid */}
          <div className="space-y-1.5">
            {Object.entries(presetIcons).map(([key, { icon: Icon, translationKey }]) => {
              const isSelected = selectedPreset === key;

              return (
                <button
                  key={key}
                  onClick={() => {
                    setSelectedPreset(isSelected ? null : key as PresetType);
                    if (!isSelected) {
                      applyPreset(key as PresetType);
                    }
                  }}
                  className={`w-full p-2 rounded-lg border text-left transition-all ${
                    isSelected
                      ? 'ring-1'
                      : ''
                  }`}
                  style={isSelected
                    ? { background: 'var(--ss-accent-warm-soft)', borderColor: 'var(--ss-brand-primary)', boxShadow: '0 0 0 1px var(--ss-brand-soft)' }
                    : { background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }
                  }
                >
                  <div className="flex items-center gap-2">
                    <div className={`p-1.5 rounded`} style={{ background: isSelected ? 'var(--ss-brand-soft)' : 'var(--ss-surface-strong)', color: isSelected ? 'var(--ss-brand-primary)' : 'var(--ss-text-subtle)' }}>
                      <Icon size={14} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <span className={`text-xs font-medium block`} style={{ color: isSelected ? 'var(--ss-brand-primary)' : 'var(--ss-text)' }}>
                        {t(`experimentBuilder.step5.presets.${translationKey}.name`)}
                      </span>
                      <p className="text-[10px] truncate" style={{ color: 'var(--ss-text-subtle)' }}>
                        {t(`experimentBuilder.step5.presets.${translationKey}.description`)}
                      </p>
                    </div>
                    <div className={`transition-transform ${isSelected ? 'rotate-90' : ''}`}>
                      <ChevronRight size={14} style={{ color: 'var(--ss-text-subtle)' }} />
                    </div>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Quick Actions */}
          <div className="flex gap-2 mt-3">
            <button
              onClick={() => {
                setSelectedPreset('full');
                applyPreset('full');
              }}
              className="flex-1 py-1.5 px-2 border rounded text-[10px] flex items-center justify-center gap-1"
              style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)', color: 'var(--ss-text-muted)' }}
            >
              <Share2 size={10} />
              {t('experimentBuilder.step5.fullyConnected')}
            </button>
            <button
              onClick={() => {
                if (agentIds.length > 0) {
                  setSelectedPreset('random');
                  applyPreset('random');
                }
              }}
              className="flex-1 py-1.5 px-2 border rounded text-[10px] flex items-center justify-center gap-1"
              style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)', color: 'var(--ss-text-subtle)' }}
            >
              <RefreshCw size={10} />
              {t('experimentBuilder.step5.reset')}
            </button>
          </div>
        </div>

        {/* Manual Links */}
        <div className="p-3 border rounded-lg shadow-sm space-y-2" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }}>
          <div className="text-xs font-semibold flex items-center gap-1.5" style={{ color: 'var(--ss-text)' }}>
            <Settings2 size={12} />
            {t('experimentBuilder.step5.manualLinks', 'Manual links')}
          </div>
          <div className="flex items-center gap-2 text-[11px]" style={{ color: 'var(--ss-text-muted)' }}>
            <select
              value={linkFrom}
              onChange={(e) => setLinkFrom(e.target.value)}
              className="flex-1 border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-brand-400"
              style={{ background: 'var(--ss-page-surface-muted)', borderColor: 'var(--ss-border)' }}
            >
              {agentIds.map((id) => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
            <span style={{ color: 'var(--ss-text-subtle)' }}>→</span>
            <select
              value={linkTo}
              onChange={(e) => setLinkTo(e.target.value)}
              className="flex-1 border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-brand-400"
              style={{ background: 'var(--ss-page-surface-muted)', borderColor: 'var(--ss-border)' }}
            >
              {agentIds.map((id) => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
          </div>
          <Button
            size="sm"
            className="w-full text-xs"
            disabled={!linkFrom || !linkTo || linkFrom === linkTo}
            onClick={addLink}
          >
            {t('experimentBuilder.step5.addLink', 'Add link')}
          </Button>

          {edges.length > 0 ? (
            <div className="max-h-60 overflow-y-auto pt-2 space-y-1 text-[11px]" style={{ borderTop: '1px solid var(--ss-border)', color: 'var(--ss-text-muted)' }}>
              {edges.map(({ key, source, target }) => (
                <div key={key} className="flex items-center justify-between px-2 py-1 rounded" style={{ background: 'var(--ss-page-surface-muted)' }}>
                  <span className="truncate">
                    {source} ↔ {target}
                  </span>
                  <button
                    className="text-[10px]"
                    onClick={() => removeLink(key)}
                  >
                    {t('common.remove', 'Remove')}
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-[10px] pt-2" style={{ color: 'var(--ss-text-subtle)', borderTop: '1px solid var(--ss-border)' }}>
              {t('experimentBuilder.step5.noLinks', 'No links yet')}
            </div>
          )}
        </div>

        {/* Parameter Controls */}
        {renderParamControls()}

        {/* Instructions */}
        <div className="text-xs leading-relaxed pt-3 border-t mt-auto" style={{ color: 'var(--ss-text-subtle)', borderColor: 'var(--ss-border)' }}>
          <strong style={{ color: 'var(--ss-text-muted)' }}>{t('experimentBuilder.step5.instructions')}:</strong>
          <ul className="list-decimal pl-4 space-y-0.5 mt-1 text-[10px]">
            <li>{t('experimentBuilder.step5.instructionSelect')}</li>
            <li>{t('experimentBuilder.step5.instructionDrag')}</li>
            <li>{t('experimentBuilder.step5.instructionZoom')}</li>
          </ul>
        </div>
      </div>

      {/* Canvas */}
      <div className="flex-1 relative overflow-hidden group min-h-[400px]" style={{ background: 'var(--ss-page-surface-muted)' }}>
        <NetworkGraph
          network={socialNetwork}
          agents={agents}
          onEdgeToggle={(source, target) => {
            const key = source < target ? `${source}|${target}` : `${target}|${source}`;
            const exists = edges.some((e) => e.key === key);
            if (exists) {
              removeLink(key);
            } else {
              const next: Record<string, string[]> = {};
              for (const id of agentIds) {
                next[id] = [...(socialNetwork[id] || [])];
              }
              if (!next[source].includes(target)) next[source].push(target);
              if (!next[target].includes(source)) next[target].push(source);
              setSocialNetwork(next);
            }
          }}
          className="w-full h-full"
        />

        {/* Network Stats */}
        <div className="absolute bottom-4 left-4 backdrop-blur-sm border rounded-lg px-3 py-2 text-[10px]" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)', color: 'var(--ss-text-muted)' }}>
          <div className="flex items-center gap-3">
            <span>
              <strong style={{ color: 'var(--ss-text)' }}>{agentIds.length}</strong> {t('experimentBuilder.step5.nodes', { count: agentIds.length })}
            </span>
            <span>
              <strong style={{ color: 'var(--ss-text)' }}>
                {Object.values(socialNetwork).reduce((sum, arr) => sum + arr.length, 0)}
              </strong> {t('experimentBuilder.step5.edges', { count: Object.values(socialNetwork).reduce((sum, arr) => sum + arr.length, 0) })}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Step5Network;
