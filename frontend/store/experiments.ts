/**
 * Experiments slice for simulation workspace.
 *
 * What/why: Manages experiment comparison, branching, reporting, and timeline control state for the simulation UI.
 * Key exports: createExperimentsSlice (Zustand slice factory).
 * Used by: SimulationPage, ExperimentDesignModal, ReportModal, ComparisonView.
 */

import { StateCreator } from 'zustand';
import type { ExperimentVariant, SimulationReport, SocialNetwork, SimNode } from '../types';
import * as experimentsApi from '../services/experiments';
import type { EnvironmentSuggestion } from '../services/environmentSuggestions';
import { addTime } from './helpers';
import { listMetrics, computeMetricTrajectories, hydrateAgentHistoryFromLogs, filterLogsToSelectedBranch } from '../utils/resultsComputations';
import { buildSummaryPrompt } from '../utils/summaryPrompt';
import { extractApiErrorMessage, getBackendErrorDetail } from '../utils/apiError';
import i18n from '../i18n';

export interface ExperimentsSlice {
  // Comparison state
  compareTargetNodeId: string | null;
  isCompareMode: boolean;
  comparisonUseLLM: boolean;

  // Cross-slice state (included here for unified updates)
  nodes?: SimNode[];
  selectedNodeId?: string | null;
  logs?: any[];
  rawEvents?: any[];
  currentSimulation?: any;
  engineConfig?: any;
  agents?: any[];
  timeConfig?: any;
  currentProviderId?: number | null;
  addNotification?: (type: string, message: string) => void;
  isGenerating?: boolean;
  isGeneratingReport?: boolean;
  selectNode?: (id: string) => void;

  // Analysis config
  analysisConfig: {
    maxEvents: number;
    samplePerRound: number;
    focusAgents: string[];
    enableLLM: boolean;
    roundStart: number | null;
    roundEnd: number | null;
  };

  // Actions
  setComparisonUseLLM: (v: boolean) => void;
  setCompareTarget: (id: string | null) => void;
  toggleCompareMode: (isOpen: boolean) => void;
  // Auto-advance
  isAutoAdvancing: boolean;
  autoAdvanceTotal: number;
  autoAdvanceCurrent: number;
  highlightedNodeId: string | null;
  startAutoAdvance: (steps: number, delayMs?: number) => Promise<void>;
  stopAutoAdvance: () => void;

  // Simulation control
  advanceSimulation: () => Promise<void>;
  branchSimulation: () => Promise<void>;
  deleteNode: () => Promise<void>;

  // Experiment execution
  runExperiment: (baseNodeId: string, name: string, variants: ExperimentVariant[]) => void;

  // Report generation
  resultsSummary: string | null;
  isGeneratingResultsSummary: boolean;
  resultsSummaryError: string | null;
  generateResultsSummary: (title: string, language: 'en' | 'zh') => Promise<void>;
  generateReport: () => Promise<void>;
  exportReport: (format: 'json' | 'md') => void;
  updateAnalysisConfig: (patch: Partial<ExperimentsSlice['analysisConfig']>) => void;
}

// Module-scope WebSocket handle to avoid duplicate connections
let _treeSocket: WebSocket | null = null;
let _treeSocketRefreshTimer: number | null = null;
const pollInterval = 1000;

const closeTreeSocket = () => {
  if (_treeSocket) {
    try { _treeSocket.close(); } catch (e) { /* ignore */ }
    _treeSocket = null;
  }
  if (_treeSocketRefreshTimer) {
    window.clearTimeout(_treeSocketRefreshTimer);
    _treeSocketRefreshTimer = null;
  }
};

export const createExperimentsSlice: StateCreator<
  ExperimentsSlice,
  [],
  [],
  ExperimentsSlice
> = (set, get) => ({
  // Initial state
  compareTargetNodeId: null,
  isCompareMode: false,
  comparisonUseLLM: false,
  analysisConfig: {
    maxEvents: 800,
    samplePerRound: 5,
    focusAgents: [],
    enableLLM: false,
    roundStart: null,
    roundEnd: null
  },
  isAutoAdvancing: false,
  autoAdvanceTotal: 0,
  autoAdvanceCurrent: 0,
  highlightedNodeId: null,
  resultsSummary: null,
  isGeneratingResultsSummary: false,
  resultsSummaryError: null,

  // Actions
  updateAnalysisConfig: (patch) => {
    set((state) => ({
      analysisConfig: { ...state.analysisConfig, ...patch }
    }));
  },

  stopAutoAdvance: () => {
    set({
      isAutoAdvancing: false,
      autoAdvanceTotal: 0,
      autoAdvanceCurrent: 0,
      highlightedNodeId: null,
    } as any);
  },

  startAutoAdvance: async (steps: number, delayMs: number = 500) => {
    const state = get() as any;

    // Guards
    if (!state.currentSimulation || !state.selectedNodeId) {
      console.error('[startAutoAdvance] No simulation or node selected');
      return;
    }
    if (state.isAutoAdvancing || state.isGenerating) {
      console.warn('[startAutoAdvance] Already in progress');
      return;
    }

    // Validate and clamp inputs
    const totalSteps = Math.min(100, Math.max(1, Math.floor(steps)));
    const delay = Math.min(5000, Math.max(100, delayMs));

    set({
      isAutoAdvancing: true,
      autoAdvanceTotal: totalSteps,
      autoAdvanceCurrent: 0,
    } as any);

    for (let i = 0; i < totalSteps; i++) {
      // CRITICAL: Read fresh state on every iteration so that
      // stopAutoAdvance() is detected between steps.
      const current = get() as any;
      if (!current.isAutoAdvancing) {
        current.addNotification?.(
          'info',
          i18n.t('simPage.autoAdvanceStopped', { current: i, total: totalSteps })
        );
        return;
      }

      set({ autoAdvanceCurrent: i + 1 } as any);

      try {
        await current.advanceSimulation();

        // Highlight newly selected node
        const afterAdvance = get() as any;
        if (afterAdvance.selectedNodeId) {
          const nodeId = afterAdvance.selectedNodeId;
          set({ highlightedNodeId: nodeId } as any);

          // Clear highlight after 2 seconds
          setTimeout(() => {
            const s = get() as any;
            if (s.highlightedNodeId === nodeId) {
              set({ highlightedNodeId: null } as any);
            }
          }, 2000);
        }
      } catch (error) {
        console.error('[startAutoAdvance] Step failed:', error);
        (get() as any).addNotification?.(
          'error',
          i18n.t('simPage.autoAdvanceError', { error: extractApiErrorMessage(error) })
        );
        set({
          isAutoAdvancing: false,
          autoAdvanceTotal: 0,
          autoAdvanceCurrent: 0,
        } as any);
        return;
      }

      // Delay between steps (skip after last step)
      if (i < totalSteps - 1) {
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }

    // All steps complete
    const final = get() as any;
    if (final.isAutoAdvancing) {
      set({
        isAutoAdvancing: false,
        autoAdvanceTotal: 0,
        autoAdvanceCurrent: 0,
      } as any);
      final.addNotification?.(
        'success',
        i18n.t('simPage.autoAdvanceComplete', { count: totalSteps })
      );
    }
  },

  setComparisonUseLLM: (v) => set({ comparisonUseLLM: v }),
  setCompareTarget: (id) => set({ compareTargetNodeId: id }),
  toggleCompareMode: (isOpen) => set({ isCompareMode: isOpen }),

  advanceSimulation: async () => {
    const state = get() as any;
    if (!state.currentSimulation || !state.selectedNodeId || state.isGenerating) return;

    const parentNode = state.nodes?.find((n: any) => n.id === state.selectedNodeId);
    if (!parentNode) {
      console.error('[advanceSimulation] Selected node not found in nodes:', state.selectedNodeId);
      state.addNotification?.('error', i18n.t('store.selectedNodeNotFound') || 'Selected node not found');
      return;
    }

    set({ isGenerating: true } as any);

    try {
      const { treeAdvanceChain, getTreeGraph, getSimEvents, getSimState } = await import('../services/simulationTree');
      const { mapBackendEventsToLogs, mapGraphToNodes, addTime, formatWorldTime } = await import('./helpers');

        const base = state.engineConfig.endpoint;
        const token = state.engineConfig.token;
        const simId = state.currentSimulation.id;
        let graphBefore = await getTreeGraph(base, simId, token);
        let parentNumeric = Number(state.selectedNodeId);

        if (!Number.isFinite(parentNumeric)) {
          if (state.selectedNodeId === 'root') {
            for (let attempt = 0; attempt < 120 && !Number.isFinite(Number(graphBefore?.root)); attempt += 1) {
              if (attempt > 0) {
                await new Promise((resolve) => setTimeout(resolve, 500));
              }
              graphBefore = await getTreeGraph(base, simId, token);
            }
          }

          const graphRoot = Number(graphBefore?.root);
          if (state.selectedNodeId === 'root' && Number.isFinite(graphRoot)) {
            parentNumeric = graphRoot;
            set({ selectedNodeId: String(graphRoot) } as any);
          } else {
            console.error('[advanceSimulation] Invalid node ID:', state.selectedNodeId, 'Type:', typeof state.selectedNodeId);
            state.addNotification?.('error', i18n.t('store.selectedNodeNotBackend') || 'Selected node is not a backend node');
            set({ isGenerating: false } as any);
            return;
          }
        }

        // Track existing children before advance to detect new ones after 504
        const existingChildIds = new Set(
          (graphBefore?.edges || []).filter((e: any) => e.from === parentNumeric).map((e: any) => e.to)
        );

        let res: { child: number };
        try {
          res = await treeAdvanceChain(base, simId, parentNumeric, 1, token);
        } catch (advanceError: any) {
          // Proxy timeout (504) — backend likely already created the child node.
          // Poll the tree graph to find the newly created child.
          console.warn('[advanceSimulation] advance_chain failed, polling graph for new child...', advanceError?.message || advanceError);
          let found: number | null = null;
          // Phase 1: find the new child. Phase 2: wait for its simulation to finish.
          // Both handled in one loop — breaks only when child is found AND no longer running.
          // 1800 attempts × 2 s = up to 1 hour, covering very long LLM runs.
          for (let attempt = 0; attempt < 1800; attempt++) {
            await new Promise((r) => setTimeout(r, 2000));
            const polledGraph = await getTreeGraph(base, simId, token);
            if (!polledGraph) continue;
            if (found == null) {
              const newChild = polledGraph.edges.find(
                (e: any) => e.from === parentNumeric && !existingChildIds.has(e.to)
              );
              if (newChild) found = newChild.to;
            }
            // Break only when found AND simulation complete (not in running set)
            if (found != null && !(polledGraph.running || []).includes(found)) {
              break;
            }
          }
          if (found == null) {
            throw advanceError;
          }
          res = { child: found };
          console.log('[advanceSimulation] Recovered from 504 — found and awaited child node', found);
        }

        const newSelectedId = String(res.child);
        set({ selectedNodeId: newSelectedId } as any);

        // Refresh tree graph
        const graph = await getTreeGraph(base, simId, token);
        if (graph) {
          const nodesMapped = mapGraphToNodes(graph);
          set({ nodes: nodesMapped } as any);
        }

        let events: any[] = [];
        let simState: any = null;
        try {
          [events, simState] = await Promise.all([
            getSimEvents(base, simId, res.child, token),
            getSimState(base, simId, res.child, token)
          ]);
        } catch (error) {
          console.error('[advanceSimulation] Advance succeeded but failed to hydrate child node:', error);
          set({ isGenerating: false } as any);
          const detail = getBackendErrorDetail(error);
          const base = i18n.t('store.advanceHydrationFailed') || 'Simulation advanced, but loading the new node details failed';
          state.addNotification?.('warning', detail !== null ? `${base}: ${detail}` : base);
          return;
        }

        console.log('[advanceSimulation] Received simState from backend');
        console.log('[advanceSimulation] simState.agents:', JSON.stringify(simState?.agents?.map((a: any) => ({ name: a.name, knowledgeBase: a.knowledgeBase })), null, 2));

        // Extract social_network from scene_config and update currentSimulation
        const socialNetwork = simState?.scene_config?.social_network || {};
        if (Object.keys(socialNetwork).length > 0) {
          console.log('[advanceSimulation] Found social_network in scene_config:', socialNetwork);
          set((s: any) => ({
            currentSimulation: { ...s.currentSimulation!, socialNetwork }
          }));
        }

        const turnVal = Number(simState?.turns ?? 0) || 0;

        // Map agents from simState, including knowledgeBase updates
        const agentsMapped: any[] = (simState?.agents || []).map((a: any, idx: number) => {
          const existing = state.agents?.find((ex: any) => ex.name === a.name);
          const fallbackRole = a.properties && (a.properties.role || a.properties.title || a.properties.position);
          const fallbackProfile = a.profile || a.user_profile || a.userProfile || (a.properties && (a.properties.profile || a.properties.description)) || existing?.profile || '';
          return {
            id: existing?.id || `a-${idx}-${a.name}`,
            name: a.name,
            role: a.role || fallbackRole || '',
            avatarUrl: existing?.avatarUrl || `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || String(idx))}`,
            profile: fallbackProfile,
            llmConfig: existing?.llmConfig || { provider: 'mock', model: 'default' },
            properties: a.properties || existing?.properties || {},
            history: existing?.history || {},
            memory: (a.short_memory || []).map((m: any, j: number) => ({
              id: `m-${idx}-${j}`,
              round: turnVal,
              content: String(m.content ?? ''),
              type: (String(m.role ?? '') === 'assistant' || String(m.role ?? '') === 'user') ? 'dialogue' : 'observation',
              timestamp: new Date().toISOString()
            })),
            knowledgeBase: a.knowledgeBase || existing?.knowledgeBase || []
          };
        });

        console.log('[advanceSimulation] Mapped agents:', agentsMapped.map((a: any) => ({ name: a.name, kbCount: a.knowledgeBase?.length || 0 })));

        const eventsArray = Array.isArray(events) ? events : [];

        // Deduplicate events before adding
        const getEventKey = (ev: any): string => {
          if (typeof ev === 'string') return `str:${ev}`;
          if (!ev || typeof ev !== 'object') return `prim:${String(ev)}`;
          const evType = ev.type || ev.event_type || 'unknown';
          const data = ev.data || {};
          const agent = data.agent || '';
          const nodeId = String(ev.node ?? data.node ?? '');

          // For system_broadcast events, use text and sender as unique key
          if (evType === 'system_broadcast') {
            const text = data.text || data.message || '';
            const sender = data.sender || '';
            const eventType = data.type || '';
            return `${nodeId}:${evType}:${eventType}:${sender}:${text}`;
          }

          // For experiment_action events, include round number to distinguish actions across rounds
          // and include node id so sibling branches with the same agent/action are not collapsed.
          if (evType === 'experiment_action') {
            const round = data.round !== undefined ? String(data.round) : '';
            const agentAction = typeof data.action === 'string' ? data.action : '';
            return `${nodeId}:${evType}:${agent}:${agentAction}:round${round}`;
          }

          // Use type, agent, content, time, and action to generate unique key
          const content = typeof data.content === 'string' ? data.content.substring(0, 100) : '';
          const time = data.time || '';
          const action = data.action?.action || data.action?.name || '';
          return `${nodeId}:${evType}:${agent}:${content}:${time}:${action}`;
        };

        set((prev: any) => {
          const existingKeys = new Set((prev.rawEvents || []).map(getEventKey));
          const batchKeys = new Set<string>();
          const newEvents = eventsArray.filter((ev: any) => {
            const key = getEventKey(ev);
            if (existingKeys.has(key)) return false;
            if (batchKeys.has(key)) return false; // Dedupe within same batch
            batchKeys.add(key);
            return true;
          });

          const normalizedEvents = newEvents.map((ev: any) => (
            ev && typeof ev === 'object' && ev.node == null
              ? { ...ev, node: newSelectedId }
              : ev
          ));

          const selectedNode = (prev.nodes || []).find((n: any) => n.id === newSelectedId);
          const round = selectedNode?.depth ?? 0;

          const logsMapped = mapBackendEventsToLogs(
            normalizedEvents, // Only map new events
            newSelectedId,
            round,
            agentsMapped,
            false // Don't include all metadata when displaying
          );

          return {
            logs: [...(prev.logs || []), ...logsMapped],
            rawEvents: [...(prev.rawEvents || []), ...normalizedEvents],
            agents: agentsMapped,
            isGenerating: false
          };
        });
        return;
    } catch (e) {
      console.error('advanceSimulation failed', e);
      set({ isGenerating: false } as any);
      const detail = getBackendErrorDetail(e);
      const base = i18n.t('store.simulationAdvanceFailed') || 'Simulation advance failed';
      state.addNotification?.('error', detail !== null ? `${base}: ${detail}` : base);
    }
  },

  branchSimulation: async () => {
    const state = get() as any;
    if (!state.currentSimulation || !state.selectedNodeId) return;

    try {
      const { treeBranch, getTreeGraph } = await import('../services/simulationTree');
      const { mapGraphToNodes } = await import('./helpers');

      const base = state.engineConfig.endpoint;
      const token = state.engineConfig.token;
      const parentNumeric = Number(state.selectedNodeId);

      if (!Number.isFinite(parentNumeric)) {
        console.error('[branchSimulation] Invalid node ID:', state.selectedNodeId, 'Type:', typeof state.selectedNodeId);
        state.addNotification?.('error', i18n.t('store.selectedNodeNotBackend') || 'Selected node is not a backend node');
        return;
      }

      const result = await treeBranch(base, state.currentSimulation.id, parentNumeric, [], token);

      if (result?.child !== undefined) {
        // Refresh tree
        const graph = await getTreeGraph(base, state.currentSimulation.id, token);
        if (graph) {
          const nodesMapped = mapGraphToNodes(graph);
          set({ nodes: nodesMapped } as any);
        }
        state.addNotification?.('success', i18n.t('store.branchCreated') || 'Branch created');
      }
    } catch (e) {
      console.error('branchSimulation failed', e);
      const detail = getBackendErrorDetail(e);
      const base = i18n.t('store.backendBranchFailed') || 'Branch creation failed';
      state.addNotification?.('error', detail !== null ? `${base}: ${detail}` : base);
    }
  },

  deleteNode: async () => {
    const state = get() as any;
    const selectedNode = (state.nodes || []).find((n: any) => String(n.id) === String(state.selectedNodeId));
    const isRootNode = !selectedNode || selectedNode.parentId == null || state.selectedNodeId === 'root';
    if (!state.currentSimulation || !state.selectedNodeId || isRootNode) {
      state.addNotification?.('error', i18n.t('store.cannotDeleteRoot') || 'Cannot delete root node');
      return;
    }

    try {
      const { treeDeleteSubtree } = await import('../services/simulationTree');
      await treeDeleteSubtree(
        state.engineConfig.endpoint,
        state.currentSimulation.id,
        Number(state.selectedNodeId),
        state.engineConfig.token
      );

      // Refresh tree
      const { getTreeGraph } = await import('../services/simulationTree');
      const { mapGraphToNodes } = await import('./helpers');
      const graph = await getTreeGraph(
        state.engineConfig.endpoint,
        state.currentSimulation.id,
        state.engineConfig.token
      );
      if (graph) {
        const mapped = mapGraphToNodes(graph);
        const rootId = mapped.find((n: any) => n.parentId == null)?.id || 'root';
        set({ nodes: mapped, selectedNodeId: rootId });
      }
      state.addNotification?.('success', i18n.t('store.nodeDeleted') || 'Node deleted');
    } catch (e) {
      console.error('deleteNode failed', e);
      const detail = getBackendErrorDetail(e);
      const base = i18n.t('store.failedToDeleteNode') || 'Failed to delete node';
      state.addNotification?.('error', detail !== null ? `${base}: ${detail}` : base);
    }
  },

  runExperiment: (baseNodeId, experimentName, variants) => {
    const state = get() as any;
    if (!state.currentSimulation) return;

    const baseNode = state.nodes?.find((n: any) => n.id === baseNodeId);
    if (!baseNode) return;

    const parentNumeric = Number(baseNode.id);
    if (!Number.isFinite(parentNumeric)) {
      state.addNotification?.('error', i18n.t('store.selectedNodeNotBackend') || 'Selected node is not a backend node');
      return;
    }
    // Variant nodes branch FROM the base node (not alongside it)
    const expectedVariantParentId = String(baseNode.id);
    const existingChildIds = new Set(
      (state.nodes || [])
        .filter((n: any) => String(n.parentId) === expectedVariantParentId)
        .map((n: any) => String(n.id))
    );

    // Call backend create + run
    (async () => {
        try {
          const simId = state.currentSimulation!.id;
          const token = (state.engineConfig as any).token as string | undefined;

          // prepare variant specs for backend (ops expected by backend)
          const variantSpecs = variants.map((v) => ({ name: v.name, ops: v.ops || [] }));

          // Step 1: create experiment (with 504 recovery)
          let createRes: any;
          try {
            createRes = await experimentsApi.createExperiment(simId, experimentName, parentNumeric, variantSpecs);
          } catch (createError: any) {
            // Proxy timeout (504) — backend likely created the experiment already.
            // Poll experiments list to find it by name.
            console.warn('[runExperiment] createExperiment failed, polling for experiment...', createError?.message || createError);
            for (let attempt = 0; attempt < 15; attempt++) {
              await new Promise((r) => setTimeout(r, 2000));
              try {
                const list = await experimentsApi.listExperiments(simId);
                const found = (list?.experiments || []).find(
                  (e: any) => e.name === experimentName
                );
                if (found) {
                  createRes = { experiment_id: found.id, node_mapping: [] };
                  console.log('[runExperiment] Recovered from 504 — found experiment', found.id);
                  break;
                }
              } catch { /* continue polling */ }
            }
            if (!createRes) {
              state.addNotification?.('error', i18n.t('store.failedToStartExperiment') || 'Failed to start experiment');
              return;
            }
          }
          const expId = (createRes as any).experiment_id || (createRes as any).id || (createRes as any).experiment?.id;
          if (!expId) {
            state.addNotification?.('error', i18n.t('store.failedToStartExperiment') || 'Failed to start experiment');
            return;
          }
          const expIdStr = String(expId);

          // Make parent non-leaf immediately so UI shows branching intent
          set((s: any) => ({ nodes: (s.nodes || []).map((n: any) => (n.id === baseNodeId ? { ...n, isLeaf: false } : n)) }));

          const nowIso = new Date().toISOString();
          const dedupLogs = (logsArr: any[]) => {
            const seen = new Set<string>();
            const out: any[] = [];
            for (const l of logsArr || []) {
              if (!l) continue;
              const key = String(
                l.id
                || `${l.nodeId || ''}|${l.type || ''}|${l.round || ''}|${l.timestamp || ''}|${l.agentId || ''}|${l.content || ''}`
              );
              if (seen.has(key)) continue;
              seen.add(key);
              out.push(l);
            }
            return out;
          };

          const buildVariantCreationLogs = (childrenIds: { node_id: number | string; variant_id?: any; variant_name?: string }[]) => {
            return childrenIds.map((child, index) => {
              const variantName = child.variant_name || variants[index]?.name || `${experimentName} #${index + 1}`;
              const spec = variants[index];
              const rawOpsLines = (spec?.ops || []).length
                ? (spec?.ops || []).map((op: any, opIndex: number) => `  [${opIndex + 1}] ${JSON.stringify(op)}`)
                : ['  []'];
              const contentLines = [
                i18n.t('store.experimentBranchCreated', { experimentName, variantName }),
                `${i18n.t('store.experimentInterventionContent')}：`,
                ...rawOpsLines,
              ];
              return {
                id: `exp-create-log-${String(child.node_id)}-${index}`,
                nodeId: String(child.node_id),
                round: 0,
                type: 'SYSTEM',
                content: contentLines.join('\n'),
                timestamp: nowIso
              };
            });
          };

          state.addNotification?.('success', i18n.t('store.experimentCreatedNoRun', { name: experimentName }) || `Experiment "${experimentName}" created`);

          const { getTreeGraph, getSimEvents, getSimState } = await import('../services/simulationTree');
          const { mapGraphToNodes, mapBackendEventsToLogs } = await import('./helpers');

          const applyOptimisticChildren = (childrenIds: { node_id: number | string; variant_id?: any; variant_name?: string }[]) => {
            const variantNameByIndex = variants.map((v) => v.name);
            set((s: any) => {
              const existingNodes = s.nodes || [];
              const baseDepth = Number(baseNode.depth || 0);
              const existingIds = new Set(existingNodes.map((n: any) => String(n.id)));
              const optimisticNodes = childrenIds.flatMap((child, index) => {
                const childId = String(child.node_id);
                if (existingIds.has(childId)) return [] as any[];
                const variantName = variantNameByIndex[index] || `${experimentName} #${index + 1}`;
                const spec = variants[index];
                return [{
                  id: childId,
                  display_id: childId,
                  parentId: expectedVariantParentId,
                  name: `${experimentName}: ${variantName}`,
                  depth: baseDepth,
                  isLeaf: true,
                  status: 'pending',
                  timestamp: new Date().toLocaleTimeString(),
                  worldTime: baseNode.worldTime,
                  meta: {
                    experiment_id: expIdStr,
                    variant_id: child.variant_id,
                    variant_name: variantName,
                    experiment_name: experimentName,
                    base_node: Number(baseNode.id),
                    ops: spec?.ops || [],
                  },
                }];
              });
              if (!optimisticNodes.length) {
                return {
                  selectedNodeId: childrenIds[0]?.node_id ? String(childrenIds[0].node_id) : s.selectedNodeId,
                  logs: dedupLogs([...(s.logs || []), ...buildVariantCreationLogs(childrenIds)])
                } as any;
              }
              return {
                nodes: [...existingNodes, ...optimisticNodes],
                selectedNodeId: childrenIds[0]?.node_id ? String(childrenIds[0].node_id) : s.selectedNodeId,
                logs: dedupLogs([...(s.logs || []), ...buildVariantCreationLogs(childrenIds)])
              } as any;
            });
          };

          const applyChildrenWithLogs = async (mapped: any[], childrenIds: { node_id: number | string; variant_id?: any; variant_name?: string }[]) => {
            set((s: any) => {
              const childMetaMap = new Map<string, { variant_id?: any; variant_name?: string; ops?: any[] }>();
              childrenIds.forEach((c, index) => {
                childMetaMap.set(String(c.node_id), {
                  variant_id: c.variant_id,
                  variant_name: c.variant_name || variants[index]?.name,
                  ops: variants[index]?.ops || [],
                });
              });

              const augmented = mapped.map((n: any) => {
                const childMeta = childMetaMap.get(String(n.id));
                if (childMeta) {
                  return {
                    ...n,
                    meta: {
                      ...(n.meta || {}),
                      experiment_id: expIdStr,
                      variant_id: childMeta.variant_id,
                      variant_name: childMeta.variant_name,
                      experiment_name: experimentName,
                      base_node: Number(baseNode.id),
                      ops: childMeta.ops,
                    }
                  };
                }
                return n;
              });

              const firstChildId = childrenIds[0]?.node_id ? String(childrenIds[0].node_id) : s.selectedNodeId;
              return {
                nodes: augmented,
                selectedNodeId: firstChildId,
                logs: dedupLogs([...(s.logs || []), ...buildVariantCreationLogs(childrenIds)])
              } as any;
            });
          };

          // Fast path: create already returns node_mapping after branching
          const runMapping = (createRes as any)?.node_mapping;
          if (!Array.isArray(runMapping) || runMapping.length === 0) {
            console.warn('[createExperiment] backend returned empty node_mapping', createRes);
            state.addNotification?.('warning', i18n.t('store.experimentNodeMappingEmpty') || 'Experiment created, but backend returned no node mapping yet');
          }
          if (Array.isArray(runMapping) && runMapping.length) {
            const childrenIds = runMapping.map((m: any) => ({ node_id: m.node_id, variant_id: m.variant_id, variant_name: m.variant_name }));
            applyOptimisticChildren(childrenIds);
            const graph = await getTreeGraph(state.engineConfig.endpoint, simId, token);
            if (graph) {
              const mapped = mapGraphToNodes(graph);
              await applyChildrenWithLogs(mapped, childrenIds);
              return;
            }
          }

          // Helper: refresh graph and attempt to locate variant nodes
          const tryResolve = async (): Promise<boolean> => {
            const [graph, expDetail] = await Promise.all([
              getTreeGraph(state.engineConfig.endpoint, simId, token),
              experimentsApi.getExperiment(simId, expIdStr)
            ]);

            if (!graph) return false;
            // Reset logs once at first resolve attempt to avoid duplicates from repeated polling
            set((s: any) => ({ logs: dedupLogs(s.logs || []) } as any));
            const mapped = mapGraphToNodes(graph);
            const variantNodesFromExp = (expDetail?.experiment?.variants || []).filter((v: any) => v && v.node_id);

            // If experiment detail already has node_ids, prefer those
            if (variantNodesFromExp.length) {
              const variantIds = variantNodesFromExp.map((v: any) => String(v.node_id));
              const children = mapped.filter((n: any) => {
                  const isVariant = variantIds.includes(String(n.id));
                  if (!isVariant) return false;
                  return String(n.parentId) === expectedVariantParentId;
                });
              if (children.length === variantIds.length) {
                // attach meta and select first child; also copy variant logs onto child nodes
                await applyChildrenWithLogs(mapped, variantNodesFromExp.map((v: any) => ({ node_id: v.node_id, variant_id: v.id, variant_name: v.name })));
                return true;
              }
            }

            // Otherwise, rely on graph children order under parent
            const children = mapped
              .filter((n: any) => {
                const isUnderParent = String(n.parentId) === expectedVariantParentId;
                if (!isUnderParent) return false;
                // Only consider new siblings (exclude the baseline node and pre-existing siblings)
                const isExisting = existingChildIds.has(String(n.id)) || String(n.id) === String(baseNode.id);
                return !isExisting;
              })
              .sort((a: any, b: any) => Number(a.id) - Number(b.id));
            if (children.length >= variants.length) {
              set((s: any) => {
                return {
                  nodes: mapped,
                  selectedNodeId: String(children[0].id),
                  logs: s.logs
                } as any;
              });
              return true;
            }

            // Update nodes anyway to reflect latest graph
            set({ nodes: mapped } as any);
            return false;
          };

          // Try immediate resolve once
          let resolved = await tryResolve();
          if (resolved) return;

          const maxAttempts = 30;
          for (let attempt = 0; attempt < maxAttempts; attempt++) {
            await new Promise((r) => setTimeout(r, pollInterval));
            resolved = await tryResolve();
            if (resolved) return;
          }

          state.addNotification?.('warning', i18n.t('store.experimentNodesTimeout') || 'Experiment nodes not available yet; please refresh or retry.');
        } catch (e) {
          console.error('Experiment error', e);
          state.addNotification?.('error', (i18n.t('store.failedToStartExperiment') || 'Failed to start experiment') + ': ' + extractApiErrorMessage(e));
        }
      })();
  },

  generateReport: async () => {
    const state = get() as any;
    if (!state.currentSimulation || !state.logs) return;

    set({ isGeneratingReport: true } as any);

    try {
      const logs = state.logs || [];
      const agents = state.agents || [];
      const analysisConfig = state.analysisConfig;

      // Filter events by round range if specified
      let filteredLogs = logs;
      if (analysisConfig.roundStart !== null) {
        filteredLogs = filteredLogs.filter((l: any) => l.round >= analysisConfig.roundStart!);
      }
      if (analysisConfig.roundEnd !== null) {
        filteredLogs = filteredLogs.filter((l: any) => l.round <= analysisConfig.roundEnd!);
      }

      // Sample events
      const maxEvents = analysisConfig.maxEvents || 800;
      const samplePerRound = analysisConfig.samplePerRound || 5;
      const roundGroups = new Map<number, any[]>();
      filteredLogs.forEach((log: any) => {
        const round = log.round || 0;
        if (!roundGroups.has(round)) roundGroups.set(round, []);
        const bucket = roundGroups.get(round)!;
        if (bucket.length < samplePerRound) {
          bucket.push(log);
        }
      });

      const sampledLogs: any[] = [];
      roundGroups.forEach((bucket) => sampledLogs.push(...bucket));

      // Build report parts
      const agentNames = agents.map((a: any) => a.name);
      const actions = sampledLogs.filter((l: any) => l.type === 'AGENT_ACTION');
      const talks = sampledLogs.filter((l: any) => l.type === 'AGENT_SAY');
      const errors = sampledLogs.filter((l: any) => l.content?.includes?.('错误') || l.content?.includes?.('error'));

      const summary = `报告生成时间: ${new Date().toLocaleString()}\n` +
        `分析事件数: ${sampledLogs.length} / ${logs.length}\n` +
        `智能体: ${agentNames.join(', ') || '无'}\n` +
        `动作数: ${actions.length}\n` +
        `对话数: ${talks.length}\n` +
        `错误数: ${errors.length}`;

      const keyEvents = sampledLogs
        .filter((l: any) => l.type !== 'AGENT_METADATA')
        .slice(0, 20)
        .map((l: any) => ({
          round: l.round,
          description: l.content?.slice(0, 100) || ''
        }));

      const agentAnalysis = agents.slice(0, 6).map((a: any) => ({
        agentName: a.name,
        analysis: `智能体 ${a.name} 的行为分析`
      }));

      let reportParts = { summary, keyEvents, agentAnalysis, suggestions: [] as string[] };

      // Try LLM refinement if enabled
      if (analysisConfig.enableLLM && state.currentProviderId) {
        try {
          const { apiClient } = await import('../services/client');
          const prompt = `你是分析员，请用中文简洁总结。\n已有摘要:\n${summary.slice(0, 800)}\n` +
            `\n关键事件:\n${keyEvents.slice(-12).map((e) => `- R${e.round}: ${e.description}`).join('\n')}\n` +
            `\n智能体分析:\n${agentAnalysis.slice(0, 6).map((a) => `- ${a.agentName}: ${a.analysis}`).join('\n')}\n` +
            `\n请输出 JSON，字段: summary(string), keyEvents([{round,description} 至多8条]), suggestions(string[] 至多6条), agentAnalysis([{agentName,analysis} 至多6条]).`;

          const res = await apiClient.post<{ text: string }>("llm/refine_report", {
            prompt,
            provider_id: state.currentProviderId
          });
          const parsed = JSON.parse(res.data.text || "{}");
          if (parsed.summary) {
            reportParts = {
              summary: parsed.summary,
              keyEvents: parsed.keyEvents || keyEvents,
              agentAnalysis: parsed.agentAnalysis || agentAnalysis,
              suggestions: parsed.suggestions || []
            };
          }
        } catch (e) {
          console.warn('LLM refinement failed, using template', e);
        }
      }

      const report: SimulationReport = {
        id: `rep-${Date.now()}`,
        generatedAt: new Date().toISOString(),
        summary: reportParts.summary,
        keyEvents: reportParts.keyEvents,
        suggestions: reportParts.suggestions,
        agentAnalysis: reportParts.agentAnalysis,
        refinedByLLM: analysisConfig.enableLLM
      };

      set((s: any) => ({
        currentSimulation: s.currentSimulation ? { ...s.currentSimulation, report } : s.currentSimulation,
        isGeneratingReport: false
      }));
      state.addNotification?.('success', i18n.t('store.reportGenerationComplete') || 'Report generation complete');
    } catch (e) {
      console.error('generateReport failed', e);
      set({ isGeneratingReport: false } as any);
      const detail = getBackendErrorDetail(e);
      const base = i18n.t('store.reportGenerationFailed') || 'Report generation failed, please try again later';
      state.addNotification?.('error', detail !== null ? `${base}: ${detail}` : base);
    }
  },

  generateResultsSummary: async (title, language) => {
    set({ isGeneratingResultsSummary: true, resultsSummaryError: null, resultsSummary: null });
    try {
      const state = get();
      const providerId = state.currentProviderId;
      if (providerId === null || providerId === undefined) {
        throw new Error('generateResultsSummary: no LLM provider selected');
      }
      const branchLogs = filterLogsToSelectedBranch(
        state.logs || [],
        state.nodes || [],
        state.selectedNodeId,
      );
      const hydratedAgents = hydrateAgentHistoryFromLogs(branchLogs, state.agents);
      const metrics = listMetrics(hydratedAgents).map((name) => ({
        name,
        series: computeMetricTrajectories(hydratedAgents, name),
      }));
      const prompt = buildSummaryPrompt({ title, language, metrics });
      const { apiClient } = await import('../services/client');
      const res = await apiClient.post<{ text: string }>('llm/refine_report', {
        prompt,
        provider_id: providerId,
      });
      const text = res.data.text;
      if (typeof text !== 'string' || text.length === 0) {
        throw new Error('generateResultsSummary: LLM returned no text');
      }
      set({ resultsSummary: text, isGeneratingResultsSummary: false });
    } catch (e) {
      const message = extractApiErrorMessage(e);
      set({ isGeneratingResultsSummary: false, resultsSummaryError: message });
      throw e;
    }
  },

  exportReport: (format) => {
    const state = get() as any;
    const report = state.currentSimulation?.report;
    if (!report) {
      state.addNotification?.('error', i18n.t('store.noReportToExport') || 'No report to export');
      return;
    }

    if (format === 'json') {
      const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${state.currentSimulation?.name || 'simulation'}_report.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      return;
    }

    // markdown export
    const lines: string[] = [];
    lines.push(`# ${i18n.t('store.simulationReport') || 'Simulation Experiment Analysis Report'}`);
    lines.push(`${i18n.t('store.generatedAt') || 'Generated at'}: ${new Date(report.generatedAt).toLocaleString()}`);
    lines.push(`\n## ${i18n.t('store.summary') || 'Summary'}\n${report.summary}`);
    lines.push(`\n## ${i18n.t('store.keyEvents') || 'Key Events'}`);
    report.keyEvents.forEach((ev) => {
      lines.push(`- R${ev.round}: ${ev.description}`);
    });
    lines.push(`\n## ${i18n.t('store.suggestions') || 'Suggestions'}`);
    report.suggestions.forEach((sug) => lines.push(`- ${sug}`));
    lines.push(`\n## ${i18n.t('store.agentAnalysis') || 'Agent Analysis'}`);
    report.agentAnalysis.forEach((a) => {
      lines.push(`- **${a.agentName}**: ${a.analysis}`);
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${state.currentSimulation?.name || 'simulation'}_report.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }
});
