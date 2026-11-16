// frontend/store/agents.ts
//
// Agent management slice.
//
// Responsibilities:
//   - Manages agent list and properties
//   - Agent profile updates
//   - Knowledge base management per agent
//   - Initial events management
//
// Used by: AgentPanel, DemographicsBuilder, any component managing agents

import { StateCreator } from 'zustand';
import type { Agent, KnowledgeItem, InitialEventItem, LogEntry } from '../types';

async function persistOverrides(
  get: () => any,
  agentName: string,
  payload: {
    language?: string;
    llm_config?: Record<string, unknown>;
    knowledge_base?: KnowledgeItem[];
    documents?: Record<string, unknown>;
    properties?: Record<string, unknown>;
    provider_id?: number | null;
  }
) {
  const state = get();

  const sim = state.currentSimulation;
  const nodeId = state.selectedNodeId;
  const base = state.engineConfig?.endpoint;
  const token = (state.engineConfig as any)?.token;

  if (!sim || nodeId == null || !base) return;

  const { applyNodeOverrides } = await import('../services/simulationTree');
  const nodeNum = Number(nodeId);
  if (!Number.isFinite(nodeNum)) return;

  await applyNodeOverrides(base, sim.id, nodeNum, [
    { name: agentName, ...payload }
  ], token).catch(() => undefined);
}

export interface AgentsSlice {
  // State
  agents: Agent[];
  initialEvents: InitialEventItem[];

  // Agent actions
  setAgents: (agents: Agent[]) => void;
  updateAgentProperty: (agentId: string, property: string, value: any) => void;
  updateAgentProfile: (agentId: string, profile: string) => void;
  updateAgentLLM: (agentId: string, llmConfig: { provider: string; model: string; provider_id: number }) => void;

  // Knowledge base actions
  addKnowledgeToAgent: (agentId: string, item: KnowledgeItem) => void;
  removeKnowledgeFromAgent: (agentId: string, itemId: string) => void;
  updateKnowledgeInAgent: (agentId: string, itemId: string, updates: Partial<KnowledgeItem>) => void;

  // Initial events actions
  addInitialEvent: (title: string, content: string, imageUrl?: string, audioUrl?: string, videoUrl?: string) => void;
}

export const createAgentsSlice: StateCreator<
  AgentsSlice,
  [],
  [],
  AgentsSlice
> = (set, get) => ({
  // Initial state
  agents: [],
  initialEvents: [],

  // Agent actions
  setAgents: (agents) => set({ agents }),

  updateAgentProperty: (agentId, property, value) => {
    set((state) => ({
      agents: state.agents.map((a) => {
        if (a.id === agentId) {
          return { ...a, properties: { ...a.properties, [property]: value } };
        }
        return a;
      })
    }));

    const agentName = get().agents.find((a) => a.id === agentId)?.name || agentId;
    const agent = get().agents.find((a) => a.id === agentId);
    // Access injectLog and addNotification via get() - they exist in other slices
    const injectLog = (get() as any).injectLog;
    const addNotification = (get() as any).addNotification;
    injectLog?.('HOST_INTERVENTION', `Host 修改了 ${agentName} 的属性 [${property}] 为 ${value}`);
    addNotification?.('success', '智能体属性已更新');

    if (agent) {
      const payload: any = { properties: { ...agent.properties, [property]: value } };
      if (property === 'language') {
        payload.language = value;
      }
      persistOverrides(get, agent.name, payload);
    }
  },

  updateAgentProfile: (agentId, profile) => {
    set((state) => ({
      agents: state.agents.map((a) => (a.id === agentId ? { ...a, profile } : a))
    }));
    const agentName = get().agents.find((a) => a.id === agentId)?.name || agentId;
    const injectLog = (get() as any).injectLog;
    const addNotification = (get() as any).addNotification;
    injectLog?.('HOST_INTERVENTION', `Host 更新了 ${agentName} 的个人简介`);
    addNotification?.('success', '智能体简介已更新');
  },

  updateAgentLLM: async (agentId, llmConfig) => {
    const simulationId = (get() as any).currentSimulation?.id;
    if (!simulationId) return;

    const previousAgents = [...get().agents];

    // Optimistically update local state (agentId is agent.name)
    set((state) => ({
      agents: state.agents.map((a) =>
        (a.name === agentId || a.id === agentId)
          ? {
              ...a,
              llmConfig: { provider: llmConfig.provider, model: llmConfig.model },
              provider_id: llmConfig.provider_id,
              properties: { ...a.properties, provider_id: llmConfig.provider_id },
            }
          : a
      )
    }));

    try {
      const { updateAgentLLMConfig } = await import('../services/simulations');
      await updateAgentLLMConfig(simulationId, agentId, {
        provider: llmConfig.provider,
        model: llmConfig.model,
        provider_id: llmConfig.provider_id,
      });

      const agent = get().agents.find((a) => a.name === agentId || a.id === agentId);
      if (agent) {
        await persistOverrides(get, agent.name, {
          llm_config: { provider: llmConfig.provider, model: llmConfig.model },
          provider_id: llmConfig.provider_id,
          properties: { ...agent.properties, provider_id: llmConfig.provider_id },
        });
      }

      const agentName = get().agents.find((a) => a.name === agentId || a.id === agentId)?.name || agentId;
      const injectLog = (get() as any).injectLog;
      const addNotification = (get() as any).addNotification;
      injectLog?.('HOST_INTERVENTION', `Host updated ${agentName}'s LLM to ${llmConfig.provider}/${llmConfig.model}`);
      addNotification?.('success', 'components.agentPanel.llmUpdateSuccess');
    } catch (error) {
      console.error('Failed to update agent LLM:', error);
      // Rollback to previous state
      set({ agents: previousAgents });
      const addNotification = (get() as any).addNotification;
      addNotification?.('error', 'components.agentPanel.llmUpdateError');
    }
  },

  // Knowledge base actions
  addKnowledgeToAgent: (agentId, item) => {
    set((state) => ({
      agents: state.agents.map((a) => {
        if (a.id === agentId) {
          return { ...a, knowledgeBase: [...a.knowledgeBase, item] };
        }
        return a;
      })
    }));
    const agentName = get().agents.find((a) => a.id === agentId)?.name || agentId;
    const agent = get().agents.find((a) => a.id === agentId);
    const injectLog = (get() as any).injectLog;
    const addNotification = (get() as any).addNotification;
    injectLog?.('HOST_INTERVENTION', `Host 给 ${agentName} 添加了知识: ${item.title}`);
    addNotification?.('success', '知识已添加');

    if (agent) {
      const kb = [...(agent.knowledgeBase || []), item];
      persistOverrides(get, agent.name, { knowledge_base: kb });
    }
  },

  removeKnowledgeFromAgent: (agentId, itemId) => {
    set((state) => ({
      agents: state.agents.map((a) => {
        if (a.id === agentId) {
          return { ...a, knowledgeBase: a.knowledgeBase.filter((k) => k.id !== itemId) };
        }
        return a;
      })
    }));
    const addNotification = (get() as any).addNotification;
    addNotification?.('success', '知识已移除');

    const agent = get().agents.find((a) => a.id === agentId);
    if (agent) {
      const kb = (agent.knowledgeBase || []).filter((k) => k.id !== itemId);
      persistOverrides(get, agent.name, { knowledge_base: kb });
    }
  },

  updateKnowledgeInAgent: (agentId, itemId, updates) => {
    set((state) => ({
      agents: state.agents.map((a) => {
        if (a.id === agentId) {
          return {
            ...a,
            knowledgeBase: a.knowledgeBase.map((k) =>
              k.id === itemId ? { ...k, ...updates } : k
            )
          };
        }
        return a;
      })
    }));
    const addNotification = (get() as any).addNotification;
    addNotification?.('success', '知识已更新');

    const agent = get().agents.find((a) => a.id === agentId);
    if (agent) {
      const kb = (agent.knowledgeBase || []).map((k) =>
        k.id === itemId ? { ...k, ...updates } : k
      );
      persistOverrides(get, agent.name, { knowledge_base: kb });
    }
  },

  // Initial events actions
  addInitialEvent: (title, content, imageUrl, audioUrl, videoUrl) => {
    const id = `init-${Date.now()}`;
    const newEvent: InitialEventItem = { id, title, content, imageUrl, audioUrl, videoUrl };
    const selectedNodeId = (get() as any).selectedNodeId;
    const logs = (get() as any).logs || [];

    set((state) => ({
      initialEvents: [...(state.initialEvents || []), newEvent]
    }));

    // If connected to backend, also broadcast as an environment event so agents receive it
    const currentSimulation = (get() as any).currentSimulation;
    if (currentSimulation?.id) {
      (async () => {
        try {
          const { applyEnvironmentEvent } = await import('../services/environmentSuggestions');
          await applyEnvironmentEvent(currentSimulation.id, {
            event_type: 'initial_event',
            description: `[初始事件] ${title}\n${content}`,
            severity: 'mild',
            node_id: selectedNodeId,
          });
        } catch (e) {
          console.error('Failed to broadcast initial event', e);
          const addNotification = (get() as any).addNotification;
          addNotification?.('error', '初始事件广播失败');
        }
      })();
    }

    // Also add to logs via the logs slice
    const setLogs = (get() as any).setLogs;
    if (setLogs && selectedNodeId) {
      setLogs([
        ...logs,
        {
          id,
          nodeId: selectedNodeId,
          round: 0,
          type: 'ENVIRONMENT',
          content: `[初始事件] ${title}\n${content}` +
            (audioUrl ? `\n[audio: ${audioUrl}]` : '') +
            (videoUrl ? `\n[video: ${videoUrl}]` : ''),
          imageUrl,
          audioUrl,
          videoUrl,
          timestamp: new Date().toISOString()
        }
      ]);
    }

    const addNotification = (get() as any).addNotification;
    addNotification?.('success', '初始事件已保存');
  }
});
