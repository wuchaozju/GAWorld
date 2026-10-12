import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSimulationStore } from '../store';
import { X, Network, Save, RefreshCw, Circle, Share2, Shuffle, Move, Users, Waypoints, Target, GitBranch, MapPin, ChevronRight, Play, Settings2, Loader2 } from 'lucide-react';
import { SocialNetwork } from '../types';
import NetworkGraph from './NetworkGraph';

// Type definitions for preset parameters
type PresetType = 'full' | 'core-periphery' | 'holme-kim' | 'waxman' | 'random' | 'sbm' | 'newman-watts' | null;

interface PresetParams {
  'core-periphery': {
    influencerPercent: number;
    influencerConnectivity: number;
    influencerReach: number;
    regularConnectivity: number;
  };
  'holme-kim': {
    newConnections: number;
    clusteringChance: number;
  };
  waxman: {
    maxDistance: number;
    distanceEffect: number;
  };
  random: {
    connectionChance: number;
  };
  sbm: {
    groupSize: number;
    withinGroupConnectivity: number;
    bridgeConnections: number;
  };
  'newman-watts': {
    neighborsEachSide: number;
    shortcutChance: number;
  };
}

// Default parameters for each preset
const defaultParams: PresetParams = {
  'core-periphery': {
    influencerPercent: 0.2,
    influencerConnectivity: 1.0,
    influencerReach: 0.3,
    regularConnectivity: 0.02,
  },
  'holme-kim': {
    newConnections: 3,
    clusteringChance: 0.5,
  },
  waxman: {
    maxDistance: 0.4,
    distanceEffect: 0.3,
  },
  random: {
    connectionChance: 0.3,
  },
  sbm: {
    groupSize: 5,
    withinGroupConnectivity: 1.0,
    bridgeConnections: 1,
  },
  'newman-watts': {
    neighborsEachSide: 2,
    shortcutChance: 0.1,
  },
};

// Preset metadata (icons, names, descriptions)
// Will be initialized with translation keys in the component
const presetIcons: Record<string, React.ElementType> = {
  full: Share2,
  random: Shuffle,
  'newman-watts': Waypoints,
  sbm: Users,
  waxman: MapPin,
  'core-periphery': Target,
  'holme-kim': GitBranch,
};

// Slider component for parameters
const ParamSlider: React.FC<{
  labelKey: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  isInteger?: boolean;
}> = ({ labelKey, value, min, max, step, onChange, isInteger }) => {
  const { t } = useTranslation();
  const displayValue = isInteger ? Math.round(value) : value.toFixed(2);

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium" style={{ color: 'var(--ss-heading)' }}>{t(`components.networkEditorModal.${labelKey}`)}</span>
        </div>
        <span className="text-xs font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--ss-page-surface-inset)', color: 'var(--ss-text-muted)' }}>
          {displayValue}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-1.5 rounded-lg appearance-none cursor-pointer accent-brand-600"
        style={{ background: 'var(--ss-border)' }}
      />
      <div className="flex justify-between text-[10px]" style={{ color: 'var(--ss-text-subtle)' }}>
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  );
};

export const NetworkEditorModal: React.FC = () => {
  const { t } = useTranslation();
  const isOpen = useSimulationStore(state => state.isNetworkEditorOpen);
  const toggle = useSimulationStore(state => state.toggleNetworkEditor);
  const currentSim = useSimulationStore(state => state.currentSimulation);
  const agents = useSimulationStore(state => state.agents);
  const updateSocialNetwork = useSimulationStore(state => state.updateSocialNetwork);

  const [network, setNetwork] = useState<SocialNetwork>({});
  const [selectedPreset, setSelectedPreset] = useState<PresetType>(null);
  const [params, setParams] = useState<PresetParams>(defaultParams);
  const [isSaving, setIsSaving] = useState(false);
  const [linkFrom, setLinkFrom] = useState('');
  const [linkTo, setLinkTo] = useState('');

  useEffect(() => {
    if (agents.length === 0) return;
    const names = agents.map((a) => a.name);
    if (!names.includes(linkFrom)) setLinkFrom(names[0]);
    if (!names.includes(linkTo)) setLinkTo(names[Math.min(1, names.length - 1)]);
  }, [agents, linkFrom, linkTo]);

  // Build presetMeta from translations
  const presetMeta: Record<string, { icon: React.ElementType; name: string; description: string }> = {
    full: {
      icon: presetIcons.full,
      name: t('components.networkEditorModal.fullyConnected'),
      description: t('components.networkEditorModal.everyoneConnected'),
    },
    random: {
      icon: presetIcons.random,
      name: t('components.networkEditorModal.random'),
      description: t('components.networkEditorModal.connectionsRandomly'),
    },
    'newman-watts': {
      icon: presetIcons['newman-watts'],
      name: t('components.networkEditorModal.smallWorld'),
      description: t('components.networkEditorModal.neighborsPlusShortcuts'),
    },
    sbm: {
      icon: presetIcons.sbm,
      name: t('components.networkEditorModal.stochasticBlock'),
      description: t('components.networkEditorModal.tightGroupsFewBridges'),
    },
    waxman: {
      icon: presetIcons.waxman,
      name: t('components.networkEditorModal.waxman'),
      description: t('components.networkEditorModal.closerAgentsConnectMore'),
    },
    'core-periphery': {
      icon: presetIcons['core-periphery'],
      name: t('components.networkEditorModal.corePeriphery'),
      description: t('components.networkEditorModal.fewHighlyConnected'),
    },
    'holme-kim': {
      icon: presetIcons['holme-kim'],
      name: t('components.networkEditorModal.holmeKim'),
      description: t('components.networkEditorModal.popularAgentsMoreConnections'),
    },
  };
  

  // Initialize network from store on open
  useEffect(() => {
    if (isOpen && currentSim) {
      let networkFromStore = currentSim.socialNetwork || {};

      // Migration: Convert old ID-based keys to name-based keys
      // Check if network keys look like old generated IDs (start with 'gen_' or don't match any agent name)
      const agentNames = new Set(agents.map(a => a.name));
      const needsMigration = Object.keys(networkFromStore).some(
        key => !agentNames.has(key) && (key.startsWith('gen_') || key.includes('_'))
      );

      if (needsMigration) {
        console.log('[NETWORK-DEBUG] Migrating old ID-based network to name-based');
        const migratedNetwork: SocialNetwork = {};

        // Create a mapping from old IDs to agent names
        const idToName: Record<string, string> = {};
        agents.forEach(agent => {
          idToName[agent.id] = agent.name;
        });

        // Migrate the network
        Object.entries(networkFromStore).forEach(([sourceId, targets]) => {
          const sourceName = idToName[sourceId] || sourceId;
          if (!agentNames.has(sourceName)) return; // Skip if agent no longer exists

          const migratedTargets: string[] = [];
          (Array.isArray(targets) ? targets : []).forEach((targetId: string) => {
            const targetName = idToName[targetId] || targetId;
            if (agentNames.has(targetName)) {
              migratedTargets.push(targetName);
            }
          });

          migratedNetwork[sourceName] = migratedTargets;
        });

        networkFromStore = migratedNetwork;
        // Save the migrated network back to store
        updateSocialNetwork(migratedNetwork).catch(() => {
          // If save fails, just use the migrated network locally
          console.log('[NETWORK-DEBUG] Failed to save migrated network, using locally');
        });
      }

      console.log('[NETWORK-DEBUG] NetworkEditorModal: Initializing network from store:', networkFromStore);
      setNetwork(networkFromStore);
    }
  }, [isOpen, currentSim]);

  // Update a specific parameter
  const updateParam = <T extends keyof PresetParams>(
    preset: T,
    key: keyof PresetParams[T],
    value: number
  ) => {
    setParams(prev => ({
      ...prev,
      [preset]: {
        ...prev[preset],
        [key]: value,
      },
    }));
  };

  // Reset parameters to defaults
  const resetParams = (preset: keyof PresetParams) => {
    setParams(prev => ({
      ...prev,
      [preset]: defaultParams[preset],
    }));
  };

  // Apply Presets with current parameters
  const applyPreset = (type: NonNullable<PresetType>) => {
    const newNetwork: SocialNetwork = {};
    const agentIds = agents.map(a => a.name); // Use agent names, not temporary IDs
    const n = agentIds.length;

    // Initialize all as empty
    agentIds.forEach(id => newNetwork[id] = []);

    if (type === 'full') {
      // Fully connected graph - every agent connected to every other agent
      agentIds.forEach(id => {
        newNetwork[id] = agentIds.filter(target => target !== id);
      });

    } else if (type === 'core-periphery') {
      const { influencerPercent, influencerConnectivity, influencerReach, regularConnectivity } = params['core-periphery'];
      const coreSize = Math.max(2, Math.floor(n * influencerPercent));
      
      const isCore = (idx: number) => idx < coreSize;
      
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          let prob: number;
          
          if (isCore(i) && isCore(j)) {
            prob = influencerConnectivity;
          } else if (isCore(i) || isCore(j)) {
            prob = influencerReach;
          } else {
            prob = regularConnectivity;
          }
          
          if (Math.random() < prob) {
            newNetwork[agentIds[i]].push(agentIds[j]);
            newNetwork[agentIds[j]].push(agentIds[i]);
          }
        }
      }

    } else if (type === 'holme-kim') {
      const { newConnections, clusteringChance } = params['holme-kim'];
      const mClamped = Math.min(newConnections, n - 1);
      
      // Start with seed
      const seedSize = mClamped + 1;
      for (let i = 0; i < seedSize; i++) {
        for (let j = i + 1; j < seedSize; j++) {
          newNetwork[agentIds[i]].push(agentIds[j]);
          newNetwork[agentIds[j]].push(agentIds[i]);
        }
      }
      
      for (let i = seedSize; i < n; i++) {
        const newNode = agentIds[i];
        const connected = new Set<string>();
        
        // First connection: preferential attachment
        let totalDegree = 0;
        for (let j = 0; j < i; j++) totalDegree += newNetwork[agentIds[j]].length;
        
        let r = Math.random() * totalDegree;
        let firstTarget = agentIds[0];
        for (let j = 0; j < i; j++) {
          r -= newNetwork[agentIds[j]].length;
          if (r <= 0) { firstTarget = agentIds[j]; break; }
        }
        
        newNetwork[newNode].push(firstTarget);
        newNetwork[firstTarget].push(newNode);
        connected.add(firstTarget);
        
        // Remaining connections
        while (connected.size < mClamped && connected.size < i) {
          if (Math.random() < clusteringChance) {
            // Triad formation: connect to neighbor of last connected
            const lastConnected = Array.from(connected).pop()!;
            const neighbors = newNetwork[lastConnected].filter(
              nb => !connected.has(nb) && nb !== newNode
            );
            if (neighbors.length > 0) {
              const triadTarget = neighbors[Math.floor(Math.random() * neighbors.length)];
              newNetwork[newNode].push(triadTarget);
              newNetwork[triadTarget].push(newNode);
              connected.add(triadTarget);
              continue;
            }
          }
          
          // Preferential attachment fallback
          r = Math.random() * totalDegree;
          for (let j = 0; j < i; j++) {
            if (connected.has(agentIds[j])) continue;
            r -= newNetwork[agentIds[j]].length;
            if (r <= 0) {
              newNetwork[newNode].push(agentIds[j]);
              newNetwork[agentIds[j]].push(newNode);
              connected.add(agentIds[j]);
              break;
            }
          }
        }
      }

    } else if (type === 'waxman') {
      const { maxDistance, distanceEffect } = params.waxman;
      
      const positions: Record<string, {x: number, y: number}> = {};
      agentIds.forEach(id => {
        positions[id] = { x: Math.random(), y: Math.random() };
      });
      
      const maxDist = Math.sqrt(2); // Diagonal of unit square
      
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const id1 = agentIds[i];
          const id2 = agentIds[j];
          const dx = positions[id1].x - positions[id2].x;
          const dy = positions[id1].y - positions[id2].y;
          const dist = Math.sqrt(dx*dx + dy*dy);
          
          const prob = distanceEffect * Math.exp(-dist / (maxDistance * maxDist));
          if (Math.random() < prob) {
            newNetwork[id1].push(id2);
            newNetwork[id2].push(id1);
          }
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

    } else if (type === 'sbm') {
      const { groupSize, withinGroupConnectivity, bridgeConnections } = params.sbm;
      const groupSizeClamped = Math.max(1, Math.round(groupSize));
      
      // Each agent has (n - groupSize) potential between-group partners
      const pBetween = Math.min(1, bridgeConnections / Math.max(1, n - groupSizeClamped));
      
      // Assign each agent to a group
      const agentGroup: Record<string, number> = {};
      agentIds.forEach((id, idx) => {
        agentGroup[id] = Math.floor(idx / groupSizeClamped);
      });
      
      // Within-group connections (all directed pairs)
      for (let i = 0; i < n; i++) {
        for (let j = 0; j < n; j++) {
          if (i === j) continue;
          const sourceId = agentIds[i];
          const targetId = agentIds[j];
          if (agentGroup[sourceId] !== agentGroup[targetId]) continue;
          
          if (Math.random() < withinGroupConnectivity) {
            if (!newNetwork[sourceId].includes(targetId)) {
              newNetwork[sourceId].push(targetId);
            }
          }
        }
      }
      
      // Between-group connections
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const sourceId = agentIds[i];
          const targetId = agentIds[j];
          if (agentGroup[sourceId] === agentGroup[targetId]) continue;
          
          if (Math.random() < pBetween) {
            if (!newNetwork[sourceId].includes(targetId)) {
              newNetwork[sourceId].push(targetId);
            }
            if (!newNetwork[targetId].includes(sourceId)) {
              newNetwork[targetId].push(sourceId);
            }
          }
        }
      }

    } else if (type === 'newman-watts') {
      const { neighborsEachSide, shortcutChance } = params['newman-watts'];
      const kClamped = Math.min(Math.round(neighborsEachSide), Math.floor((n - 1) / 2));
      
      // Step 1: Create ring lattice with k neighbors on each side
      agentIds.forEach((id, idx) => {
        for (let offset = 1; offset <= kClamped; offset++) {
          const prevIdx = (idx - offset + n) % n;
          const nextIdx = (idx + offset) % n;
          
          if (!newNetwork[id].includes(agentIds[prevIdx])) {
            newNetwork[id].push(agentIds[prevIdx]);
          }
          if (!newNetwork[id].includes(agentIds[nextIdx])) {
            newNetwork[id].push(agentIds[nextIdx]);
          }
        }
      });
      
      // Step 2: Add random shortcuts
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const sourceId = agentIds[i];
          const targetId = agentIds[j];
          
          if (newNetwork[sourceId].includes(targetId)) continue;
          
          if (Math.random() < shortcutChance) {
            newNetwork[sourceId].push(targetId);
            newNetwork[targetId].push(sourceId);
          }
        }
      }
    }

    setNetwork(newNetwork);
  };

  const toggleConnection = (source: string, target: string) => {
    if (source === target) return;
    const srcLinks = new Set(network[source] || []);
    const tgtLinks = new Set(network[target] || []);

    if (srcLinks.has(target) || tgtLinks.has(source)) {
      srcLinks.delete(target);
      tgtLinks.delete(source);
    } else {
      srcLinks.add(target);
      tgtLinks.add(source);
    }

    setNetwork(prev => ({
      ...prev,
      [source]: Array.from(srcLinks),
      [target]: Array.from(tgtLinks),
    }));
  };

  const edges = React.useMemo(() => {
    const list: { key: string; source: string; target: string }[] = [];
    const dedup = new Set<string>();
    Object.entries(network).forEach(([source, targets]) => {
      targets.forEach((target) => {
        if (!agents.find((a) => a.name === source) || !agents.find((a) => a.name === target)) return;
        const key = source < target ? `${source}|${target}` : `${target}|${source}`;
        if (dedup.has(key)) return;
        dedup.add(key);
        list.push({ key, source, target });
      });
    });
    return list;
  }, [network, agents]);

  const addLink = () => {
    if (!linkFrom || !linkTo || linkFrom === linkTo) return;
    toggleConnection(linkFrom, linkTo);
  };

  const removeLink = (key: string) => {
    const [a, b] = key.split('|');
    toggleConnection(a, b);
  };


  const handleSave = async () => {
    setIsSaving(true);
    console.log('[NETWORK-DEBUG] NetworkEditorModal: Saving network:', network);
    try {
      await updateSocialNetwork(network);
      toggle(false);
    } finally {
      setIsSaving(false);
    }
  };

  // Render parameter controls based on selected preset
  const renderParamControls = () => {
    if (!selectedPreset || selectedPreset === 'full') return null;

    const presetKey = selectedPreset as keyof PresetParams;
    
    return (
      <div className="space-y-3 p-3 rounded-lg border shadow-sm" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }}>
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold flex items-center gap-1.5" style={{ color: 'var(--ss-heading)' }}>
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

        {selectedPreset === 'core-periphery' && (
          <div className="space-y-3">
            <ParamSlider
              labelKey="fractionOfInfluencers"
              value={params['core-periphery'].influencerPercent}
              min={0.05}
              max={0.5}
              step={0.05}
              onChange={(v) => updateParam('core-periphery', 'influencerPercent', v)}
            />
            <ParamSlider
              labelKey="connectionProbabilityInfluencers"
              value={params['core-periphery'].influencerConnectivity}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => updateParam('core-periphery', 'influencerConnectivity', v)}
            />
            <ParamSlider
              labelKey="influencerToRegularConnection"
              value={params['core-periphery'].influencerReach}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => updateParam('core-periphery', 'influencerReach', v)}
            />
            <ParamSlider
              labelKey="connectionProbabilityRegular"
              value={params['core-periphery'].regularConnectivity}
              min={0}
              max={0.5}
              step={0.01}
              onChange={(v) => updateParam('core-periphery', 'regularConnectivity', v)}
            />
          </div>
        )}

        {selectedPreset === 'holme-kim' && (
          <div className="space-y-3">
            <ParamSlider
              labelKey="connectionsPerNewAgent"
              value={params['holme-kim'].newConnections}
              min={1}
              max={10}
              step={1}
              onChange={(v) => updateParam('holme-kim', 'newConnections', v)}
              isInteger
            />
            <ParamSlider
              labelKey="probabilityOfTriangles"
              value={params['holme-kim'].clusteringChance}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => updateParam('holme-kim', 'clusteringChance', v)}
            />
          </div>
        )}

        {selectedPreset === 'waxman' && (
          <div className="space-y-3">
            <ParamSlider
              labelKey="maximumDistance"
              value={params.waxman.maxDistance}
              min={0.1}
              max={1}
              step={0.05}
              onChange={(v) => updateParam('waxman', 'maxDistance', v)}
            />
            <ParamSlider
              labelKey="distanceReduction"
              value={params.waxman.distanceEffect}
              min={0.1}
              max={1}
              step={0.05}
              onChange={(v) => updateParam('waxman', 'distanceEffect', v)}
            />
          </div>
        )}

        {selectedPreset === 'random' && (
          <div className="space-y-3">
            <ParamSlider
              labelKey="probabilityAnyTwoConnect"
              value={params.random.connectionChance}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => updateParam('random', 'connectionChance', v)}
            />
          </div>
        )}

        {selectedPreset === 'sbm' && (
          <div className="space-y-3">
            <ParamSlider
              labelKey="agentsPerCommunity"
              value={params.sbm.groupSize}
              min={2}
              max={20}
              step={1}
              onChange={(v) => updateParam('sbm', 'groupSize', v)}
              isInteger
            />
            <ParamSlider
              labelKey="connectionProbabilityWithinGroup"
              value={params.sbm.withinGroupConnectivity}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => updateParam('sbm', 'withinGroupConnectivity', v)}
            />
            <ParamSlider
              labelKey="averageConnectionsOtherGroups"
              value={params.sbm.bridgeConnections}
              min={0}
              max={5}
              step={0.5}
              onChange={(v) => updateParam('sbm', 'bridgeConnections', v)}
            />
          </div>
        )}

        {selectedPreset === 'newman-watts' && (
          <div className="space-y-3">
            <ParamSlider
              labelKey="neighborsEachSide"
              value={params['newman-watts'].neighborsEachSide}
              min={1}
              max={10}
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

        {/* Generate Button */}
        <button
          onClick={() => applyPreset(selectedPreset)}
          className="w-full py-2 bg-brand-600 text-white text-xs font-medium rounded-lg hover:bg-brand-700 transition-colors flex items-center justify-center gap-1.5 shadow-sm"
        >
          <Play size={12} />
          {t('components.networkEditorModal.generateNetwork')}
        </button>
      </div>
    );
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[140] flex items-start justify-center overflow-y-auto p-4 backdrop-blur-sm sm:p-6" style={{ background: 'var(--ss-overlay)' }}>
      <div className="my-auto flex max-h-[calc(100vh-2rem)] w-full max-w-5xl flex-col overflow-hidden rounded-xl shadow-2xl animate-in zoom-in-95 duration-200 sm:max-h-[calc(100vh-3rem)]" style={{ background: 'var(--ss-page-surface)', border: '1px solid var(--ss-border)' }}>
        <div className="px-6 py-4 border-b flex justify-between items-center" style={{ background: 'var(--ss-page-surface-muted)', borderColor: 'var(--ss-border)' }}>
          <div>
            <h2 className="text-lg font-bold flex items-center gap-2" style={{ color: 'var(--ss-heading)' }}>
              <Network className="text-brand-600" size={20} />
              {t('components.networkEditorModal.title')}
            </h2>
            <p className="text-xs mt-1" style={{ color: 'var(--ss-text-muted)' }}>{t('components.networkEditorModal.description')}</p>
          </div>
          <button onClick={() => toggle(false)} className="hover:opacity-80" style={{ color: 'var(--ss-text-subtle)' }}>
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 flex overflow-hidden">
          {/* Sidebar Tools */}
          <div className="w-72 border-r p-4 space-y-4 flex flex-col overflow-y-auto" style={{ background: 'var(--ss-page-surface-muted)', borderColor: 'var(--ss-border)' }}>
            <div>
              <label className="text-xs font-bold uppercase tracking-wide" style={{ color: 'var(--ss-text-muted)' }}>
                {t('components.networkEditorModal.networkPresets')}
              </label>
              <p className="text-[10px] mt-0.5 mb-3" style={{ color: 'var(--ss-text-subtle)' }}>
                {t('components.networkEditorModal.selectPresetHint')}
              </p>

              {/* Preset Selection Grid */}
              <div className="space-y-1.5">
                {Object.entries(presetMeta).map(([key, meta]) => {
                  const Icon = meta.icon;
                  const isSelected = selectedPreset === key;

                  return (
                    <button
                      key={key}
                      onClick={() => setSelectedPreset(isSelected ? null : key as PresetType)}
                      className={`w-full p-2.5 rounded-lg border text-left transition-all ${
                        isSelected
                          ? 'bg-brand-50 border-brand-300 ring-1 ring-brand-200'
                          : ''
                      }`}
                      style={!isSelected ? { background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' } : undefined}
                    >
                      <div className="flex items-center gap-2">
                        <div className={`p-1.5 rounded ${isSelected ? 'bg-brand-100 text-brand-600' : ''}`}
                             style={!isSelected ? { background: 'var(--ss-page-surface-inset)', color: 'var(--ss-text-muted)' } : undefined}>
                          <Icon size={14} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <span className={`text-xs font-medium block ${isSelected ? 'text-brand-700' : ''}`}
                                style={!isSelected ? { color: 'var(--ss-heading)' } : undefined}>
                            {meta.name}
                          </span>
                          <p className="text-[10px] truncate mt-0.5" style={{ color: 'var(--ss-text-subtle)' }}>
                            {meta.description}
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
                  className="flex-1 py-1.5 px-2 border rounded text-[10px] hover:opacity-90 flex items-center justify-center gap-1"
                  style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)', color: 'var(--ss-text-muted)' }}
                >
                  <Share2 size={10} />
                  {t('components.networkEditorModal.fullyConnected')}
                </button>
                <button
                  onClick={() => setNetwork({})}
                  className="flex-1 py-1.5 px-2 border rounded text-[10px] hover:opacity-90 flex items-center justify-center gap-1"
                  style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)', color: 'var(--ss-text-muted)' }}
                >
                  <Circle size={10} />
                  {t('components.networkEditorModal.clear')}
                </button>
              </div>

              {/* Manual Links */}
              <div className="p-3 border rounded-lg shadow-sm space-y-2 mt-3" style={{ background: 'var(--ss-page-surface)', borderColor: 'var(--ss-border)' }}>
                <div className="text-xs font-semibold flex items-center gap-1.5" style={{ color: 'var(--ss-heading)' }}>
                  <Settings2 size={12} />
                  {t('components.networkEditorModal.manualLinks')}
                </div>
                <div className="flex items-center gap-2 text-[11px]" style={{ color: 'var(--ss-text-muted)' }}>
                  <select
                    value={linkFrom}
                    onChange={(e) => setLinkFrom(e.target.value)}
                    className="flex-1 border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-brand-400"
                    style={{ background: 'var(--ss-page-surface-inset)', borderColor: 'var(--ss-border)', color: 'var(--ss-text)' }}
                  >
                    <option value="">{t('components.networkEditorModal.selectSource')}</option>
                    {agents.map((a) => (
                      <option key={a.id} value={a.name}>{a.name}</option>
                    ))}
                  </select>
                  <span style={{ color: 'var(--ss-text-subtle)' }}>↔</span>
                  <select
                    value={linkTo}
                    onChange={(e) => setLinkTo(e.target.value)}
                    className="flex-1 border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-brand-400"
                    style={{ background: 'var(--ss-page-surface-inset)', borderColor: 'var(--ss-border)', color: 'var(--ss-text)' }}
                  >
                    <option value="">{t('components.networkEditorModal.selectTarget')}</option>
                    {agents.map((a) => (
                      <option key={a.id} value={a.name}>{a.name}</option>
                    ))}
                  </select>
                </div>
                <button
                  onClick={addLink}
                  disabled={!linkFrom || !linkTo || linkFrom === linkTo}
                  className="w-full py-1.5 text-xs bg-brand-500 text-white rounded hover:bg-brand-600 disabled:opacity-50"
                >
                  {t('components.networkEditorModal.addLink')}
                </button>

                {edges.length > 0 ? (
                  <div className="max-h-32 overflow-y-auto border-t pt-2 space-y-1 text-[11px]"
                       style={{ borderColor: 'var(--ss-border)', color: 'var(--ss-text-muted)' }}>
                    {edges.map(({ key, source, target }) => (
                      <div key={key} className="flex items-center justify-between px-2 py-1 rounded" style={{ background: 'var(--ss-page-surface-inset)' }}>
                        <span className="truncate">{source} ↔ {target}</span>
                        <button
                          className="text-red-500 text-[10px] hover:text-red-600"
                          onClick={() => removeLink(key)}
                        >
                          {t('common.remove')}
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-[10px] border-t pt-2" style={{ color: 'var(--ss-text-subtle)', borderColor: 'var(--ss-border)' }}>
                    {t('components.networkEditorModal.noLinks')}
                  </div>
                )}
              </div>
            </div>

            {/* Parameter Controls */}
            {renderParamControls()}

            {/* Instructions */}
            <div className="text-xs leading-relaxed pt-3 border-t mt-auto" style={{ color: 'var(--ss-text-subtle)', borderColor: 'var(--ss-border)' }}>
              <strong style={{ color: 'var(--ss-text-muted)' }}>{t('components.networkEditorModal.instructions')}:</strong>
              <ul className="list-decimal pl-4 space-y-0.5 mt-1 text-[10px]">
                <li>{t('components.networkEditorModal.instruction1')}</li>
                <li>{t('components.networkEditorModal.instruction2')}</li>
                <li>{t('components.networkEditorModal.instruction3')}</li>
                <li>{t('components.networkEditorModal.instruction4')}</li>
                <li>{t('components.networkEditorModal.instruction5')}</li>
              </ul>
              <div className="mt-2 flex items-center gap-1 text-[10px] bg-blue-50 text-blue-600 p-2 rounded">
                <Move size={12} />
                <span>{t('components.networkEditorModal.zoomPanHint')}</span>
              </div>
            </div>
          </div>

          {/* Canvas */}
          <div className="flex-1 relative overflow-hidden group" style={{ background: 'var(--ss-page-surface-inset)' }}>
            <NetworkGraph network={network} agents={agents} onEdgeToggle={(s, t) => toggleConnection(s, t)} className="w-full h-full" />

            {/* Network Stats */}
            <div className="absolute bottom-4 left-4 backdrop-blur-sm rounded-lg px-3 py-2 text-[10px]"
                 style={{ background: 'color-mix(in srgb, var(--ss-page-surface) 90%, transparent)', border: '1px solid var(--ss-border)', color: 'var(--ss-text-muted)' }}>
              <div className="flex items-center gap-3">
                <span>
                  <strong style={{ color: 'var(--ss-heading)' }}>{agents.length}</strong> {t('components.networkEditorModal.nodes')}
                </span>
                <span>
                  <strong style={{ color: 'var(--ss-heading)' }}>
                    {edges.length}
                  </strong> {t('components.networkEditorModal.edges')}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="px-6 py-4 border-t flex justify-end gap-3" style={{ background: 'var(--ss-page-surface-muted)', borderColor: 'var(--ss-border)' }}>
          <button onClick={() => toggle(false)} className="px-4 py-2 text-sm font-medium rounded-lg" style={{ color: 'var(--ss-text-muted)' }}
            onMouseOver={(e) => e.currentTarget.style.background = 'var(--ss-page-surface-inset)'}
            onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}>
            {t('common.cancel')}
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="px-6 py-2 text-sm bg-brand-600 text-white font-medium hover:bg-brand-700 rounded-lg shadow-sm flex items-center gap-2 disabled:cursor-not-allowed"
            style={isSaving ? { background: 'var(--ss-text-subtle)' } : undefined}
          >
            {isSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
            {isSaving ? t('components.networkEditorModal.saving') : t('components.networkEditorModal.saveTopologySettings')}
          </button>
        </div>
      </div>
    </div>
  );
};

