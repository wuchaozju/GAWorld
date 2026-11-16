// frontend/store/simulation.ts
//
// Core simulation state management slice.
//
// Responsibilities:
//   - Simulation CRUD operations
//   - Tree/node management
//   - Template management
//   - Time configuration
//   - Engine connection status
//
// Used by: All simulation-related components, Dashboard, SimulationPage

import { StateCreator } from 'zustand';
import type {
  Simulation,
  SimNode,
  TimeConfig,
  SimulationTemplate,
  Agent,
  EngineConfig,
  SocialNetwork
} from '../types';
import { SYSTEM_TEMPLATES, generateNodes, mapGraphToNodes, DEFAULT_TIME_CONFIG, mapBackendEventsToLogs } from './helpers';
import { getApiBase } from '../services/base';
import i18n from '../i18n';
import type { Provider } from '../services/providers';
import { selectSerializedNodeId } from '../services/simulationSnapshots';

export interface SimulationSlice {
  // State
  simulations: Simulation[];
  currentSimulation: Simulation | null;
  nodes: SimNode[];
  selectedNodeId: string | null;
  savedTemplates: SimulationTemplate[];
  timeConfig: TimeConfig;
  engineConfig: EngineConfig;

  // Cross-slice state (included here for unified updates)
  agents?: Agent[];
  logs?: any[];
  rawEvents?: any[];
  isWizardOpen?: boolean;
  llmProviders?: Provider[];
  currentProviderId?: number | null;
  selectedProviderId?: number | null;
  addNotification?: (type: 'success' | 'error' | 'info', message: string) => void;

  // Actions
  setSimulation: (sim: Simulation) => void;
  addSimulation: (name: string, template: SimulationTemplate, customAgents?: Agent[], timeConfig?: TimeConfig) => void;
  updateTimeConfig: (config: TimeConfig) => void;
  saveTemplate: (name: string, description: string) => void;
  deleteTemplate: (id: string) => void;
  exitSimulation: () => void;
  resetSimulation: () => Promise<void>;
  deleteSimulation: () => Promise<void>;
  selectNode: (id: string) => Promise<void>;
  updateSocialNetwork: (network: SocialNetwork) => Promise<void>;
  loadSimulations: () => Promise<void>;
  loadSimulationById: (id: string) => Promise<void>;
}

export const createSimulationSlice: StateCreator<
  SimulationSlice,
  [],
  [],
  SimulationSlice
> = (set, get) => ({
  // Initial state
  simulations: [],
  currentSimulation: null,
  nodes: generateNodes(),
  selectedNodeId: 'root',
  savedTemplates: [...SYSTEM_TEMPLATES],
  timeConfig: DEFAULT_TIME_CONFIG,
  engineConfig: {
    endpoint: getApiBase(),
    status: 'disconnected',
    token: import.meta.env?.VITE_API_TOKEN || undefined
  },

  // Actions
  setSimulation: (sim) => set({
    currentSimulation: sim,
    resultsSummary: null,
    isGeneratingResultsSummary: false,
    resultsSummaryError: null,
  }),

  loadSimulations: async () => {
    try {
      const { listSimulations } = await import('../services/simulations');
      const simulations = await listSimulations();
      set({ simulations });
    } catch (e) {
      console.error('Failed to load simulations', e);
    }
  },

  loadSimulationById: async (id: string) => {
    if (!id) return;

    const state = get();
    const base = state.engineConfig.endpoint;
    const token = (state.engineConfig as any).token;
    const llmProviders = state.llmProviders || [];

    // Helper to convert provider_id to llmConfig
    const buildLLMConfig = (agent: any) => {
      // If llmConfig already exists and is valid, use it
      // Check both camelCase (llmConfig) and snake_case (llm_config)
      const llmConfig = agent.llmConfig || agent.llm_config;
      if (llmConfig && llmConfig.provider && llmConfig.model) {
        console.log(`[buildLLMConfig] Agent ${agent.name}: Using existing llmConfig:`, llmConfig);
        return llmConfig;
      }

      // Try to get provider_id from properties, root, or camelCase variant
      const providerId = agent.properties?.provider_id || agent.provider_id || agent.providerId;

      console.log(`[buildLLMConfig] Agent ${agent.name}: provider_id=${providerId}, available providers:`, llmProviders.length);

      if (providerId != null && llmProviders.length > 0) {
        const provider = llmProviders.find((p: any) => p.id === Number(providerId));
        if (provider) {
          const config = {
            provider: provider.provider || provider.name,
            model: provider.model || 'default'
          };
          console.log(`[buildLLMConfig] Agent ${agent.name}: Found provider:`, config);
          return config;
        } else {
          console.warn(`[buildLLMConfig] Agent ${agent.name}: Provider ID ${providerId} not found in providers list`);
        }
      }

      // Fallback to default
      console.warn(`[buildLLMConfig] Agent ${agent.name}: Using fallback default config`);
      return { provider: 'backend', model: 'default' };
    };

    try {
      const { getSimulation } = await import('../services/simulations');
      const { getTreeGraph, getSimState, getSimEvents, getRehydrate } = await import('../services/simulationTree');

      const sim = await getSimulation(id);

      const graph = await getTreeGraph(base, id, token).catch(() => null);

      if (graph && graph.root != null) {
        const nodes = mapGraphToNodes(graph);

        let savedId: string | null = null;
        try { savedId = localStorage.getItem('fos_selectedNodeId'); } catch { /* noop */ }
        const savedNodeExists = savedId && nodes.some((n) => n.id === savedId);

        const runningId = Array.isArray(graph.running) && graph.running.length > 0 ? graph.running[0] : null;
        const frontierId = Array.isArray(graph.frontier) && graph.frontier.length > 0 ? graph.frontier[0] : null;
        const deepestLeaf = nodes.reduce<{ id: string | null; depth: number }>((acc, n) => {
          const depthNum = Number(n.depth ?? 0);
          if (n.isLeaf && depthNum >= acc.depth) {
            return { id: n.id, depth: depthNum };
          }
          return acc;
        }, { id: null, depth: -Infinity });

        const selectedId = savedNodeExists
          ? savedId!
          : runningId != null
          ? String(runningId)
          : frontierId != null
          ? String(frontierId)
          : deepestLeaf.id ?? String(graph.root);

        const nodeNumeric = Number(selectedId);
        const simState = Number.isFinite(nodeNumeric)
          ? await getSimState(base, id, nodeNumeric, token).catch(() => null)
          : null;
        const events = Number.isFinite(nodeNumeric)
          ? await getSimEvents(base, id, nodeNumeric, token).catch(() => [])
          : [];

        if (simState) {
          const turnVal = Number(simState?.turns ?? 0) || 0;
          const agents = (simState?.agents || []).map((a: any, idx: number) => {
            const fallbackRole = a.properties && (a.properties.role || a.properties.title || a.properties.position);
            const fallbackProfile = a.profile || a.user_profile || a.userProfile || (a.properties && (a.properties.profile || a.properties.description)) || '';
            return {
              id: `a-${idx}-${a.name}`,
              name: a.name,
              role: a.role || fallbackRole || '',
              avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || String(idx))}`,
              profile: fallbackProfile,
              llmConfig: buildLLMConfig(a),
              properties: a.properties || {},
              history: {},
              memory: (a.short_memory || []).map((m: any, j: number) => ({
                id: `m-${idx}-${j}`,
                round: turnVal,
                content: String(m.content ?? ''),
                type: (String(m.role ?? '') === 'assistant' || String(m.role ?? '') === 'user') ? 'dialogue' : 'observation',
                timestamp: new Date().toISOString()
              })),
              knowledgeBase: a.knowledgeBase || []
            };
          });

          const socialNetwork = simState?.scene_config?.social_network || (sim as any).scene_config?.social_network || {};
          const logs = mapBackendEventsToLogs(events || [], selectedId, turnVal, agents, true);

          set({
            currentSimulation: { ...sim, socialNetwork },
            nodes,
            selectedNodeId: selectedId,
            agents,
            rawEvents: events || [],
            logs
          });
          return;
        }
      }

      // Fallback 1: rehydrate snapshot (includes nodes/agents)
      try {
        const re = await getRehydrate(base, id, token).catch(() => null);
        if (re && typeof re === 'object') {
          const nodesRaw2 = (re.nodes || []) as any[];
          const nodes2: SimNode[] = nodesRaw2.map((n: any) => ({
            id: String(n.id),
            display_id: String(n.id),
            parentId: n.parent == null ? null : String(n.parent),
            name: String(i18n.t('simPage.nodeId', { id: n.id })),
            depth: Number(n.depth || 0),
            isLeaf: (n.depth || 0) === (Math.max(...(nodesRaw2.map((x: any) => x.depth || 0))) || 0),
            status: 'completed' as const,
            timestamp: new Date().toLocaleTimeString(),
            worldTime: new Date().toISOString(),
            meta: n.meta || {}
          }));

          const selectedSnapshotNodeId = selectSerializedNodeId(nodesRaw2);
          let agents2: any[] = [];
          try {
            const firstNode = nodesRaw2.find((n: any) => String(n.id) === selectedSnapshotNodeId);
            const simSnap2 = firstNode?.sim || {};
            const latestAgents2 = simSnap2?.agents || re.agents || [];
            if (Array.isArray(latestAgents2)) {
              agents2 = latestAgents2.map((a: any, idx: number) => ({
                id: `a-${idx}-${a.name}`,
                name: a.name,
                role: a.role || (a.properties || {}).role || '',
                avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || String(idx))}`,
                profile: '',
                llmConfig: buildLLMConfig(a),
                properties: a.properties || {},
                history: {},
                memory: (a.short_memory || []).map((m: any, j: number) => ({ id: `m-${idx}-${j}`, round: Number(simSnap2?.turns || 1), content: String(m.content ?? ''), type: 'dialogue', timestamp: new Date().toISOString() })),
                knowledgeBase: a.knowledgeBase || []
              }));
            } else if (latestAgents2 && typeof latestAgents2 === 'object') {
              agents2 = Object.keys(latestAgents2).map((k: string, idx: number) => {
                const a = (latestAgents2 as any)[k] || {};
                return {
                  id: `a-${idx}-${a.name || k}`,
                  name: a.name || k,
                  role: a.role || (a.properties || {}).role || '',
                  avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || k)}`,
                  profile: '',
                  llmConfig: buildLLMConfig(a),
                  properties: a.properties || {},
                  history: {},
                  memory: (a.short_memory || []).map((m: any, j: number) => ({ id: `m-${idx}-${j}`, round: Number(simSnap2?.turns || 0), content: String(m.content ?? ''), type: 'dialogue', timestamp: new Date().toISOString() })),
                  knowledgeBase: a.knowledgeBase || []
                };
              });
            }
          } catch (e) {
            console.warn('rehydrate parsing failed', e);
          }

          if (nodes2.length > 0) {
            set({
              currentSimulation: sim,
              nodes: nodes2,
              selectedNodeId: selectedSnapshotNodeId,
              agents: agents2,
              rawEvents: [],
              logs: []
            });
            return;
          }
        }
      } catch (e) {
        console.warn('rehydrate fallback failed', e);
      }

      // Fallback 2: persisted latest_state on the simulation object
      try {
        const latest = (sim as any).latest_state;
        if (latest && typeof latest === 'object') {
          const nodesRaw = (latest.nodes || []) as any[];
          const nodes: SimNode[] = nodesRaw.map((n: any) => ({
            id: String(n.id),
            display_id: String(n.id),
            parentId: n.parent == null ? null : String(n.parent),
            name: String(i18n.t('simPage.nodeId', { id: n.id })),
            depth: Number(n.depth || 0),
            isLeaf: (n.depth || 0) === (Math.max(...(nodesRaw.map((x: any) => x.depth || 0))) || 0),
            status: 'completed' as const,
            timestamp: new Date().toLocaleTimeString(),
            worldTime: new Date().toISOString(),
            meta: n.meta || {}
          }));

          const selectedSnapshotNodeId = selectSerializedNodeId(nodesRaw);
          let agents: any[] = [];
          if (Array.isArray(nodesRaw)) {
            const matched = nodesRaw.find((n: any) => String(n.id) === selectedSnapshotNodeId);
            const simSnap = matched?.sim || {};
            const latestAgents = simSnap?.agents || latest.agents || [];
            if (latestAgents && typeof latestAgents === 'object') {
              if (Array.isArray(latestAgents)) {
                agents = latestAgents.map((a: any, idx: number) => ({
                  id: `a-${idx}-${a.name}`,
                  name: a.name,
                  role: a.role || (a.properties || {}).role || '',
                  avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || String(idx))}`,
                  profile: '',
                  llmConfig: { provider: 'mock', model: 'default' },
                  properties: a.properties || {},
                  history: {},
                  memory: (a.short_memory || []).map((m: any, j: number) => ({ id: `m-${idx}-${j}`, round: Number(simSnap?.turns || 0), content: String(m.content ?? ''), type: 'dialogue', timestamp: new Date().toISOString() })),
                  knowledgeBase: a.knowledgeBase || []
                }));
              } else {
                agents = Object.keys(latestAgents).map((k: string, idx: number) => {
                  const a = (latestAgents as any)[k] || {};
                  return {
                    id: `a-${idx}-${a.name || k}`,
                    name: a.name || k,
                    role: a.role || (a.properties || {}).role || '',
                    avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || k)}`,
                    profile: '',
                    llmConfig: { provider: 'mock', model: 'default' },
                    properties: a.properties || {},
                    history: {},
                    memory: (a.short_memory || []).map((m: any, j: number) => ({ id: `m-${idx}-${j}`, round: Number(simSnap?.turns || 0), content: String(m.content ?? ''), type: 'dialogue', timestamp: new Date().toISOString() })),
                    knowledgeBase: a.knowledgeBase || []
                  };
                });
              }
            }
          }

          const socialNetwork = latest.social_network || (sim as any).scene_config?.social_network || {};

          // Attempt to fetch events for the selected node if numeric
          let events: any[] = [];
          const selectedNodeNumeric = selectedSnapshotNodeId ? Number(selectedSnapshotNodeId) : null;
          if (selectedNodeNumeric != null && Number.isFinite(selectedNodeNumeric)) {
            events = await getSimEvents(base, id, selectedNodeNumeric, token).catch(() => []);
          }

          const logs = mapBackendEventsToLogs(events || [], nodes[0]?.id ?? 'root', Number((latest as any)?.turns ?? 0) || 0, agents, true);

          set({
            currentSimulation: { ...sim, socialNetwork },
            nodes,
            selectedNodeId: selectedSnapshotNodeId,
            agents,
            rawEvents: events || [],
            logs
          });
          return;
        }
      } catch (e) {
        console.warn('latest_state fallback failed', e);
      }

      // If everything fails, fall back to an empty shell so user can still operate
      set({
        currentSimulation: sim,
        nodes: generateNodes(),
        selectedNodeId: 'root',
        agents: [],
        rawEvents: [],
        logs: []
      });
    } catch (e) {
      console.error('Failed to load simulation by id', e);
      set({ currentSimulation: null, nodes: generateNodes(), selectedNodeId: 'root', agents: [], rawEvents: [] });
      (get() as any).addNotification?.('error', i18n.t('store.failedToLoadSimulation') || 'Failed to load simulation');
    }
  },

  addSimulation: (name, template, customAgents, timeConfig) => {
    const state = get();

    // Translation helper using i18n instance
    const t = (key: string, params?: Record<string, any>) => String(i18n.t(key, params));

    // Helper function to generate default agents
    const generateDefaultAgents = (templateType: string): Agent[] => {
      if (templateType === 'council') {
        return Array.from({ length: 5 }).map((_, i): Agent => ({
          id: `c${i + 1}`,
          name: i === 0 ? t('store.agents.chairman') : `${t('store.agents.councilor')} ${String.fromCharCode(65 + i - 1)}`,
          role: i === 0 ? 'Chairman' : 'Council Member',
          avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=council${i}`,
          profile: t('store.agents.councilProfile'),
          llmConfig: { provider: 'OpenAI', model: 'gpt-4o' },
          properties: {
            [t('store.properties.influence')]: 50 + Math.floor(Math.random() * 40),
            [t('store.properties.tendency')]: i % 2 === 0 ? t('store.properties.conservative') : t('store.properties.radical'),
            [t('store.properties.pressure')]: 20
          },
          history: {},
          memory: [],
          knowledgeBase: []
        }));
      }

      if (templateType === 'werewolf') {
        const roles = [
          t('store.agents.judge'),
          t('store.agents.seer'),
          t('store.agents.witch'),
          t('store.agents.hunter'),
          t('store.agents.werewolf'),
          t('store.agents.werewolf'),
          t('store.agents.villager'),
          t('store.agents.villager'),
          t('store.agents.villager')
        ];
        return roles.map((role, i): Agent => ({
          id: `w${i + 1}`,
          name: i === 0 ? 'God' : `${t('store.agents.player')} ${i}`,
          role,
          avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=werewolf${i}`,
          profile: `${t('store.agents.roleIs')} ${role}`,
          llmConfig: { provider: 'OpenAI', model: 'gpt-4o' },
          properties: { [t('store.properties.alive')]: 1, [t('store.properties.suspicion')]: 10 },
          history: {},
          memory: [],
          knowledgeBase: []
        }));
      }

      // Default village agents
      return [
        {
          id: 'a1',
          name: t('store.agents.alice'),
          role: t('store.agents.mayor'),
          avatarUrl: 'https://picsum.photos/200/200',
          profile: t('store.agents.aliceProfile'),
          llmConfig: { provider: 'OpenAI', model: 'gpt-4o' },
          properties: {
            [t('store.properties.trust')]: 85,
            [t('store.properties.stress')]: 40,
            [t('store.properties.money')]: 1200
          },
          history: {},
          memory: [],
          knowledgeBase: []
        } as Agent,
        {
          id: 'a2',
          name: t('store.agents.bob'),
          role: t('store.agents.merchant'),
          avatarUrl: 'https://picsum.photos/201/201',
          profile: t('store.agents.bobProfile'),
          llmConfig: { provider: 'Anthropic', model: 'claude-4-5-sonnet' },
          properties: {
            [t('store.properties.trust')]: 45,
            [t('store.properties.stress')]: 20,
            [t('store.properties.money')]: 5000
          },
          history: {},
          memory: [],
          knowledgeBase: []
        } as Agent
      ];
    };

    // Prepare agents
    let finalAgents = customAgents;
    if (!finalAgents) {
      if (template.agents && template.agents.length > 0) {
        finalAgents = JSON.parse(JSON.stringify(template.agents));
      } else {
        finalAgents = generateDefaultAgents(template.sceneType);
      }
    }

    // Apply custom template actions to agents if present
    // Note: ExperimentBuilderModal sets 'actions' (not 'availableActions')
    const templateActions = (template as any).genericConfig?.actions || [];
    if (templateActions.length > 0 && finalAgents) {
      finalAgents = finalAgents.map(agent => ({
        ...agent,
        action_space: templateActions
      }));
    }

    const finalTimeConfig = timeConfig || template.defaultTimeConfig || DEFAULT_TIME_CONFIG;

    (async () => {
      try {
        const { createSimulation, startSimulation } = await import('../services/simulations');
        const { getTreeGraph } = await import('../services/simulationTree');

        const base = state.engineConfig.endpoint;
        const token = (state.engineConfig as any).token;

          const mapSceneType: Record<string, string> = {
            village: 'village_scene',
            council: 'council_experiment',  // REFACTOR-COUNCIL-06: Use new experiment scene
            werewolf: 'werewolf_scene',
            generic: 'generic_scene',
            experiment: 'experiment_template'
          };
          const backendSceneType = mapSceneType[template.sceneType] || template.sceneType;
          const isGAWorldScenario = template.genericConfig?.scenario_id === 'gaworld' || backendSceneType === 'gaworld_scene';
          const inferGAWorldAgentIds = (): string[] => {
            if (!isGAWorldScenario) return [];
            return (finalAgents || [])
              .map((agent: any) => String(agent?.id || '').trim())
              .filter((agentId: string) => agentId.length > 0);
          };

          // Determine if this is an experiment template (has structured actions)
          const isExperimentTemplate = backendSceneType === 'experiment_template' ||
            (templateActions.length > 0 && templateActions.some((a: any) => a.action_type));

          // For experiment templates, use the new structured action format
          const sceneConfig: any = {
            time_scale: finalTimeConfig,
            social_network: template.defaultNetwork || {},
            language: i18n.language || 'en',
            locale: i18n.language?.startsWith('zh') ? 'zh' : 'en',
          };

          // Provide opening notice text to backend scenes
          if (backendSceneType === 'policy_cascade_scene') {
            const openingNotice = String((template.genericConfig as any)?.parameters?.policy_text || '').trim();
            if (openingNotice) {
              sceneConfig.initial_event = openingNotice;
            } else if (template.description) {
              sceneConfig.initial_event = template.description;
            }
          } else if (backendSceneType === 'council_experiment') {
            // REFACTOR-COUNCIL-06: Council experiment configuration
            // NO DEFAULTS - fail fast if parameters are missing
            const params = (template.genericConfig as any)?.parameters;
            if (!params?.deliberation_rounds) {
              throw new Error('deliberation_rounds parameter is required for council experiment');
            }
            if (!params?.voting_threshold) {
              throw new Error('voting_threshold parameter is required for council experiment');
            }
            if (!params?.proposal_text && !template.description) {
              throw new Error('proposal_text or description is required for council experiment');
            }
            sceneConfig.deliberation_rounds = params.deliberation_rounds;
            sceneConfig.voting_threshold = params.voting_threshold;
            sceneConfig.proposal_text = params.proposal_text || template.description;
          } else if (template.description) {
            sceneConfig.initial_event = template.description;
            sceneConfig.initial_events = [template.description];
          }

          if (template.genericConfig?.parameters) {
            sceneConfig.parameters = { ...template.genericConfig.parameters };
          }

          if (isGAWorldScenario) {
            const inferredAgentIds = inferGAWorldAgentIds();
            const configuredAgentIds = String(sceneConfig.parameters?.agent_ids || '').trim();
            if (!sceneConfig.parameters) {
              sceneConfig.parameters = {};
            }
            if (!configuredAgentIds && inferredAgentIds.length > 0) {
              sceneConfig.parameters.agent_ids = inferredAgentIds.join(',');
            }
          }

          if (isExperimentTemplate && templateActions.length > 0) {
            // Use the new experiment template format
            sceneConfig.description = template.genericConfig?.description || name || 'Experiment';
            sceneConfig.scenario_id = template.genericConfig?.scenario_id || 'custom';
            sceneConfig.actions = templateActions.map((action: any) => ({
              action_type: action.action_type || action,
              name: action.name || action,
              description: action.description || `${action} action`,
              parameters: action.parameters || [],
            }));
            sceneConfig.round_visibility = template.genericConfig?.round_visibility || 'simultaneous';
            sceneConfig.settings = {
              round_visibility: template.genericConfig?.round_visibility || 'simultaneous',
            };
          } else if (templateActions.length > 0) {
            // Legacy format
            sceneConfig.available_actions = templateActions;
          }

          const payload: any = {
            scene_type: isGAWorldScenario ? 'gaworld_scene' : isExperimentTemplate ? 'experiment_template' : backendSceneType,
            scene_config: sceneConfig,
            agent_config: {
              language: i18n.language || 'en',
              agents: (finalAgents || []).map((a: any) => ({
                id: a.id,
                name: a.name,
                profile: a.profile || a.rolePrompt,  // FIX: Fall back to rolePrompt if profile is undefined
                rolePrompt: a.rolePrompt,            // ADD: Pass rolePrompt explicitly for experiment templates
                role: a.role,
                avatarUrl: a.avatarUrl,
                llmConfig: a.llmConfig || a.llm_config,  // Accept both camelCase and snake_case
                provider_id: a.provider_id,  // CRITICAL: Preserve provider_id for LLM assignment
                properties: { ...a.properties, role: a.role },
                history: a.history || {},
                memory: a.memory || [],
                knowledgeBase: a.knowledgeBase || [],
                // For experiment templates, use empty action_space (scene provides actions dynamically)
                // For other scenes, use the agent's action_space or default to ['send_message']
                action_space: isExperimentTemplate ? [] : (Array.isArray(a.action_space) ? a.action_space : ['send_message'])
              }))
            },
            llm_provider_id: state.selectedProviderId ?? state.currentProviderId ?? undefined,
            name: name || undefined
          };

          const sim = await createSimulation(base, payload, token);

          try {
            await startSimulation(base, sim.id, token);
          } catch (e) {
            console.error('[addSimulation] Failed to start simulation:', e);
          }

          const newSim: Simulation = {
            id: sim.id,
            name: name || sim.name,
            templateId: template.id,
            scene_type: sim.scene_type || (isGAWorldScenario ? 'gaworld_scene' : isExperimentTemplate ? 'experiment_template' : backendSceneType),
            status: 'active',
            createdAt: new Date().toISOString().split('T')[0],
            timeConfig: finalTimeConfig,
            socialNetwork: template.defaultNetwork || {},
            // Include scene_config so Experiment Design Modal can access parameters
            scene_config: sceneConfig
          };

          set({
            simulations: [...(get().simulations || []), newSim],
            currentSimulation: newSim,
            agents: finalAgents || [],
            logs: [],
            rawEvents: [],
            timeConfig: finalTimeConfig,
            // Reset nodes and selectedNodeId before loading the graph
            nodes: [],
            selectedNodeId: null
          });

          // Retry fetching the tree graph with exponential backoff
          // The backend might need time to initialize the tree after starting the simulation
          const maxRetries = 5;
          const baseDelay = 500;
          let graph: any = null;
          for (let attempt = 0; attempt < maxRetries; attempt++) {
            graph = await getTreeGraph(base, sim.id, token);
            if (graph && graph.root != null) {
              break;
            }
            if (attempt < maxRetries - 1) {
              await new Promise(r => setTimeout(r, baseDelay * Math.pow(2, attempt)));
            }
          }

          if (graph && graph.root != null) {
            const { mapGraphToNodes } = await import('./helpers');
            const nodesMapped = mapGraphToNodes(graph);
            set({
              nodes: nodesMapped,
              selectedNodeId: String(graph.root)
            });
          } else {
            console.error('[addSimulation] Failed to fetch tree graph after retries');
          }

          // Close the wizard
          (get() as any).toggleWizard?.(false);
          (get() as any).addNotification?.('success', t('store.simulationCreated', { name: newSim.name }));
        } catch (e) {
          console.error(e);
          (get() as any).addNotification?.('error', t('store.failedToCreateSimulation'));
        }
      })();
  },

  updateTimeConfig: (config) => {
    set({ timeConfig: config });
  },

  saveTemplate: (name, description) => {
    const currentSim = get().currentSimulation;
    if (!currentSim) return;

    const agents = (get() as any).agents || [];

    const newTemplate: SimulationTemplate = {
      id: `tpl-${Date.now()}`,
      name,
      description,
      category: 'custom',
      sceneType: 'generic',
      agents: agents,
      defaultTimeConfig: get().timeConfig,
      socialNetwork: currentSim.socialNetwork
    };

    set((state) => ({
      savedTemplates: [...state.savedTemplates, newTemplate]
    }));
    get().addNotification?.('success', '模板已保存');
  },

  deleteTemplate: (id) => {
    set((state) => ({
      savedTemplates: state.savedTemplates.filter((t) => t.id !== id)
    }));
    get().addNotification?.('success', '模板已删除');
  },

  selectNode: async (id) => {
    const state = get();
    if (state.selectedNodeId === id) return;
    set({ selectedNodeId: id });

    const sim = state.currentSimulation;
    if (!sim?.id) return;

    const nodeNumeric = Number(id);
    if (!Number.isFinite(nodeNumeric)) return;

    const base = state.engineConfig.endpoint;
    const token = (state.engineConfig as any).token;

    try {
      const { getSimEvents, getSimState } = await import('../services/simulationTree');

      const [simState, events] = await Promise.all([
        getSimState(base, sim.id, nodeNumeric, token).catch(() => null),
        getSimEvents(base, sim.id, nodeNumeric, token).catch(() => []),
      ]);

      const fresh = get();
      if (fresh.selectedNodeId !== id) return;

      if (simState) {
        const turnVal = Number(simState?.turns ?? 0) || 0;
        const agents = (simState?.agents || []).map((a: any, idx: number) => {
          const fallbackRole = a.properties && (a.properties.role || a.properties.title || a.properties.position);
          const fallbackProfile = a.profile || a.user_profile || a.userProfile || (a.properties && (a.properties.profile || a.properties.description)) || '';
          const llmProviders = fresh.llmProviders || [];
          const providerId = a.properties?.provider_id || a.provider_id || a.providerId;
          let llmConfig = a.llmConfig || a.llm_config;
          if (!llmConfig?.provider && providerId != null && llmProviders.length > 0) {
            const provider = llmProviders.find((p: any) => p.id === Number(providerId));
            if (provider) llmConfig = { provider: provider.provider || provider.name, model: provider.model || 'default' };
          }
          if (!llmConfig?.provider) llmConfig = { provider: 'backend', model: 'default' };

          return {
            id: `a-${idx}-${a.name}`,
            name: a.name,
            role: a.role || fallbackRole || '',
            avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || String(idx))}`,
            profile: fallbackProfile,
            llmConfig,
            properties: a.properties || {},
            history: {},
            memory: (a.short_memory || []).map((m: any, j: number) => ({
              id: `m-${idx}-${j}`,
              round: turnVal,
              content: String(m.content ?? ''),
              type: (String(m.role ?? '') === 'assistant' || String(m.role ?? '') === 'user') ? 'dialogue' : 'observation',
              timestamp: new Date().toISOString()
            })),
            knowledgeBase: a.knowledgeBase || []
          };
        });

        const logs = mapBackendEventsToLogs(events || [], id, turnVal, agents, true);
        set({ agents, rawEvents: events || [], logs });
      } else {
        const agents = fresh.agents || [];
        const logs = mapBackendEventsToLogs(events || [], id, 0, agents, true);
        set({ rawEvents: events || [], logs });
      }
    } catch (e) {
      console.warn('selectNode: failed to fetch events for node', id, e);
    }
  },

  updateSocialNetwork: async (network) => {
    const currentSim = get().currentSimulation;
    if (!currentSim) return;

    try {
      const { updateSimulation: updateSimApi } = await import('../services/simulations');
      // Send social_network inside scene_config, not as a top-level socialNetwork field
      // The SimulationUpdate schema has scene_config field but the frontend was sending
      // a wrong key that gets silently ignored
      await updateSimApi(currentSim.id, { scene_config: { social_network: network } });

      set((state) => ({
        currentSimulation: state.currentSimulation
          ? { ...state.currentSimulation, socialNetwork: network }
          : null
      }));
      get().addNotification?.('success', '社交网络已更新');
    } catch (e) {
      console.error('Failed to update social network', e);
      get().addNotification?.('error', '更新社交网络失败');
    }
  },

  exitSimulation: () => {
    set({
      currentSimulation: null,
      nodes: generateNodes(),
      selectedNodeId: 'root'
    });

    // Clear logs in the logs slice
    (get() as any).logs = [];
    (get() as any).rawEvents = [];

    const addNotification = (get() as any).addNotification;
    addNotification?.('info', '已退出当前模拟');
  },

  resetSimulation: async () => {
    const state = get();
    if (!state.currentSimulation) return;

    try {
      const { resetSimulation: resetSimApi } = await import('../services/simulations');
      await resetSimApi(state.currentSimulation.id);

      const { getTreeGraph } = await import('../services/simulationTree');
      const graph = await getTreeGraph(
        state.engineConfig.endpoint,
        state.currentSimulation.id,
        state.engineConfig.token
      );

      if (graph) {
        const nodesMapped = mapGraphToNodes(graph);
        set({
          nodes: nodesMapped,
          selectedNodeId: graph.root != null ? String(graph.root) : null
        });
      }

      // Clear logs
      (get() as any).logs = [];
      (get() as any).rawEvents = [];

      const addNotification = (get() as any).addNotification;
      addNotification?.('success', '模拟已重置');
    } catch (e) {
      console.error('resetSimulation failed', e);
      const addNotification = (get() as any).addNotification;
      addNotification?.('error', '重置模拟失败');
    }
  },

  deleteSimulation: async () => {
    const state = get();
    if (!state.currentSimulation) return;

    try {
      const { deleteSimulation: deleteSimApi } = await import('../services/simulations');
      await deleteSimApi(state.currentSimulation.id);

      set({
        currentSimulation: null,
        nodes: generateNodes(),
        selectedNodeId: 'root'
      });

      // Clear logs
      (get() as any).logs = [];
      (get() as any).rawEvents = [];

      const addNotification = (get() as any).addNotification;
      addNotification?.('success', '模拟已删除');
    } catch (e) {
      console.error('deleteSimulation failed', e);
      const addNotification = (get() as any).addNotification;
      addNotification?.('error', '删除模拟失败');
    }
  }
});
