// frontend/store/helpers.ts
//
// Pure helper functions for store operations.
//
// Responsibilities:
//   - Time calculation and formatting
//   - Event-to-log mapping
//   - Translation helpers for i18n
//   - Agent generation utilities
//
// Used by: Multiple store slices, components

import i18n from '../i18n';
import type { Agent, LogEntry, TimeUnit, TimeConfig, SimNode } from '../types';
import type { Graph } from '../services/simulationTree';
import { buildTranslatedActionExecution, extractSummaryParameterText, formatExperimentNarrative, formatExperimentParameters, prettifyAssistantContext, resolveAgentDisplayName, translateActionName, translateAgentContent, translateEnvText } from './helpers/agentText';
import { generateAgentsWithAI, generateAgentsWithDemographics } from './helpers/agentGeneration';
import { fetchEnvironmentSuggestions } from './helpers/legacyEnvironment';
import { SYSTEM_TEMPLATES } from './helpers/systemTemplates';

// =============================================================================
// Time Helpers
// =============================================================================

export const isZh = () => (i18n.language || 'en').toLowerCase().startsWith('zh');
export const getLocale = () => (isZh() ? 'zh-CN' : 'en-US');
export const pickText = (en: string, zh: string) => (isZh() ? zh : en);

export const addTime = (dateStr: string, value: number, unit: TimeUnit): string => {
  const date = new Date(dateStr);
  switch (unit) {
    case 'minute':
      date.setMinutes(date.getMinutes() + value);
      break;
    case 'hour':
      date.setHours(date.getHours() + value);
      break;
    case 'day':
      date.setDate(date.getDate() + value);
      break;
    case 'week':
      date.setDate(date.getDate() + value * 7);
      break;
    case 'month':
      date.setMonth(date.getMonth() + value);
      break;
    case 'year':
      date.setFullYear(date.getFullYear() + value);
      break;
  }
  return date.toISOString();
};

export const formatWorldTime = (isoString: string) => {
  const date = new Date(isoString);
  return date.toLocaleString(getLocale(), {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
};

export const DEFAULT_TIME_CONFIG: TimeConfig = {
  baseTime: new Date().toISOString(),
  unit: 'hour',
  step: 1
};

// =============================================================================
// Agent Display Helpers
// =============================================================================

const GENERIC_AGENT_LABEL = /^agent(?:\s|_)?(\d+)$/i;

const extractAgentOrdinal = (value: string): string => {
  const match = value.match(GENERIC_AGENT_LABEL);
  return match?.[1] || '';
};

const isGenericAgentLabel = (value: string): boolean => GENERIC_AGENT_LABEL.test(value.trim());

export const getAgentDisplayName = (agent: Partial<Agent> | null | undefined): string => {
  if (!agent) return pickText('Participant', '参与者');
  if (agent.name && String(agent.name).trim()) return String(agent.name).trim();
  const ordinal = agent.id ? extractAgentOrdinal(String(agent.id)) : '';
  if (ordinal) return pickText(`Participant ${ordinal}`, `${ordinal}号参与者`);
  return pickText('Participant', '参与者');
};

export const getAgentDisplayRole = (agent: Partial<Agent> | null | undefined): string => {
  if (!agent) return pickText('Participant in current simulation', '参与当前实验');
  if (agent.role && String(agent.role).trim()) return String(agent.role).trim();
  return pickText('Participant in current simulation', '参与当前实验');
};

export { resolveAgentDisplayName } from './helpers/agentText';

// =============================================================================
// Graph/Node Helpers
// =============================================================================

export const generateNodes = (): SimNode[] => {
  return [
    {
      id: 'root',
      display_id: '0',
      parentId: null,
      name: 'Start',
      depth: 0,
      isLeaf: true,
      status: 'pending',
      timestamp: new Date().toISOString(),
      worldTime: new Date().toISOString()
    }
  ];
};

export const mapGraphToNodes = (graph: Graph): SimNode[] => {
  const parentMap = new Map<number, number | null>();
  const childrenSet = new Set<number>();
  for (const edge of graph.edges) {
    parentMap.set(edge.to, edge.from);
    childrenSet.add(edge.from);
  }
  const root = graph.root;
  if (root != null && !parentMap.has(root)) parentMap.set(root, null);
  const running = new Set(graph.running || []);
  const nowIso = new Date().toISOString();
  const locale = getLocale();
  return graph.nodes.map((n) => {
    const pid = parentMap.has(n.id) ? parentMap.get(n.id)! : null;
    const isLeaf = !childrenSet.has(n.id);
    const meta = (n as any).meta || null;
    const displayName = isZh() ? `节点 ${n.id}` : `Node ${n.id}`;
    return {
      id: String(n.id),
      display_id: String(n.id),
      parentId: pid == null ? null : String(pid),
      name: displayName,
      depth: n.depth,
      isLeaf,
      status: running.has(n.id) ? 'running' : 'completed',
      timestamp: new Date().toLocaleTimeString(locale),
      worldTime: nowIso,
      meta
    };
  });
};

// =============================================================================
// Translation Helpers
// =============================================================================

export { translateActionName } from './helpers/agentText';

// =============================================================================
// Event Helpers
// =============================================================================

export const extractEventTimestamp = (ev: any, data: any, fallback: string): string => {
  const raw = data?.time || data?.timestamp || ev?.timestamp;
  if (!raw) return fallback;
  const d = new Date(raw);
  return isNaN(d.getTime()) ? fallback : d.toISOString();
};

export const pickNodeId = (ev: any, fallback: string): string => {
  const nodeVal = ev?.node;
  if (nodeVal === null || nodeVal === undefined) return fallback;
  return String(nodeVal);
};

export const pickRound = (ev: any, data: any, fallback: number): number => {
  const cand = data?.turn ?? data?.round ?? ev?.round;
  const n = Number(cand);
  return Number.isFinite(n) ? n : fallback;
};

// =============================================================================
// Event to Log Mapping (simplified version - full version in logs.ts)
// =============================================================================

export const mapBackendEventsToLogs = (
  events: any[],
  nodeId: string,
  round: number,
  agents: Agent[],
  includeAllMetadata: boolean = false
): LogEntry[] => {
  const nowIso = new Date().toISOString();
  const nameToId = new Map<string, string>();
  agents.forEach(a => nameToId.set(a.name, a.id));
  const getDisplayAgentName = (agentRef: string | undefined) => resolveAgentDisplayName(agentRef, agents);

  return (events || []).map((ev: any, i: number): LogEntry | null => {
    const evData = (ev && typeof ev === 'object' && (ev.data || ev.event_type || ev.type)) ? ev : null;
    const payload = evData ? ev.data || {} : {};
    const ts = extractEventTimestamp(ev, payload, nowIso);
    const roundVal = pickRound(ev, payload, round);
    const nodeVal = pickNodeId(ev, nodeId);

    const base: LogEntry = {
      id: `srv-${Date.now()}-${i}`,
      nodeId: nodeVal,
      round: roundVal,
      type: 'SYSTEM',
      content: '',
      timestamp: ts
    };

    if (typeof ev === 'string') {
      return { ...base, type: 'SYSTEM', content: ev };
    }
    if (!ev || typeof ev !== 'object') {
      return { ...base, type: 'SYSTEM', content: String(ev) };
    }

    const evType = ev.type || ev.event_type;
    const data = payload;
    const labels = {
      reasoningStep: (step: number) => pickText(`Starting step ${step} reasoning`, `开始第 ${step} 步推理`),
      reasoningStart: pickText('Starting reasoning', '开始推理'),
      reasoningDone: pickText('Reasoning complete', '完成推理'),
      actionPrefix: pickText('Action', '动作'),
      yieldTurn: pickText('Yielded the floor', '结束本轮发言'),
      planUpdate: pickText('Plan updated', '更新计划'),
      agentError: pickText('Agent error', '智能体发生错误'),
      llmCallError: pickText('LLM call failed', 'LLM 调用失败'),
      llmParseError: pickText('LLM output parse failed', 'LLM 输出解析失败'),
      agentOffline: pickText('Agent went offline', '智能体已掉线'),
      distortionBlocked: pickText('Policy transmission blocked', '政策传递被截留'),
      distortionAdjusted: pickText('Policy transmission distorted', '政策传递发生失真'),
      distortionUnchanged: pickText('Policy transmission stayed effectively unchanged', '政策传递基本保持原样'),
      distortedReason: pickText('Distortion reason', '已发生失真，原因'),
      pressureReason: pickText('Distortion pressure', '存在失真压力，但本次保持原样，原因'),
      distortionInput: pickText('Announcement classified as distortion cascade input', '本条公告被识别为：distortion cascade input'),
      nonDistortionInput: pickText('Announcement did not enter distortion cascade', '本条公告未进入 distortion cascade'),
      privateCascadeInput: pickText('This is a private cascade input, visible only to', '这是一条私有级联输入，仅'),
      waitingForTopTier: pickText('waiting for top-tier relay', '可见，等待其作为 top tier 下传'),
      privateBroadcast: pickText('Targeted private broadcast', '定向私有广播'),
      globalBroadcast: pickText('Global broadcast', '全局广播'),
      recipientsLabel: pickText('Recipients', '接收者'),
      allAgents: pickText('All agents', '全体智能体'),
      originalMessage: pickText('Received upstream policy version', '收到的上级政策版本'),
      draftMessage: pickText('Agent draft before scene rewrite', 'Agent 原始下传草稿'),
      finalMessage: pickText('Actual downstream message', '实际对下发送内容'),
      reasonLabel: pickText('Reason', '原因'),
      metricsLabel: pickText('Metrics', '参数/评分'),
      actionStart: pickText('Started action', '开始执行动作'),
      actionEnd: pickText('performed action', '执行了动作'),
      systemEvent: pickText('System event', '系统事件'),
      runtimeFailed: pickText('Runtime failed', '运行失败'),
      agentResponse: pickText('Agent response', 'Agent responded'),
      choseAction: (agent: string, action: string) => pickText(`${agent} chose ${action}`, `${agent} 选择了 ${action}`)
    };

    // Agent context delta
    if (evType === 'agent_ctx_delta') {
      const raw = typeof data.content === 'string' ? data.content : '';
      const role = String(data.role || '').toLowerCase();
      const agentName: string = data.agent || '';
      const agentId = agentName ? nameToId.get(agentName) : undefined;
      const displayAgentName = getDisplayAgentName(agentName);

      if (role === 'user') {
        const isBroadcastMessage = /\[(Message|消息)\]\s*[^:]+:/.test(raw);
        const isPublicEvent = /Public Event:|公共事件[:：]/.test(raw);
        if (isBroadcastMessage || isPublicEvent) {
          return null;
        }
        const text = translateEnvText(raw);
        return { ...base, type: 'SYSTEM', content: text || `[环境反馈] ${agentName || ''}` };
      }

      if (role === 'assistant') {
        // Parse the JSON response from legacy agent
        let parsed = null;
        try {
          // Try to parse as JSON
          parsed = JSON.parse(raw);
        } catch {}

        // Check if this is a run_experiment action (verbose legacy wrapper)
        if (parsed && parsed.action && parsed.action.name === 'run_experiment') {
          // Skip showing the verbose run_experiment trigger
          // The actual experiment results will be shown via experiment_action events
          return null;
        }

        // For other actions, show a cleaner format
        if (parsed) {
          const actionName = parsed.action?.name || '';
          const response = parsed.response || '';

          // If there's a meaningful response, show it
          if (response && response !== 'Hello! Nice to meet you.' && response !== 'Hello! Nice to meet you') {
            return { ...base, type: 'AGENT_SAY', agentId, content: response };
          }

          // Otherwise skip the verbose metadata
          return null;
        }

        const pretty = prettifyAssistantContext(raw);
        return { ...base, type: 'AGENT_METADATA', agentId, content: pretty || raw || labels.agentResponse };
      }

      return { ...base, type: 'SYSTEM', content: raw || `[agent_ctx_delta] ${displayAgentName}` };
    }

    // Agent process start/end - metadata only
    if (evType === 'agent_process_start' || evType === 'agent_process_end') {
      if (!includeAllMetadata) return null;
      const agentName: string = data.agent || '';
      const agentId = agentName ? nameToId.get(agentName) : undefined;
      return { ...base, type: 'AGENT_METADATA', agentId, content: labels.reasoningDone };
    }

    // Action start (yield is special)
    if (evType === 'action_start') {
      const agentName: string = data.agent || '';
      const actionData = data.action || {};

      // Handle nested action structure from legacy agent responses
      let rawName: string = '';
      if (actionData.action && typeof actionData.action === 'object') {
        rawName = actionData.action.name || '';
      } else if (actionData.name) {
        rawName = actionData.name;
      } else if (typeof actionData.action === 'string') {
        rawName = actionData.action;
      } else {
        rawName = 'unknown';
      }

      const agentId = agentName ? nameToId.get(agentName) : undefined;
      const displayAgentName = getDisplayAgentName(agentName);

      if (rawName === 'yield') {
        return { ...base, type: 'AGENT_METADATA', agentId, content: labels.yieldTurn };
      }
      if (!includeAllMetadata) return null;

      const actionName: string = translateActionName(rawName);
      return { ...base, type: 'AGENT_ACTION', agentId, content: `${displayAgentName} ${labels.actionStart} ${actionName}` };
    }

    // Plan update - metadata only
    if (evType === 'plan_update') {
      if (!includeAllMetadata) return null;
      const agentName: string = data.agent || '';
      const agentId = agentName ? nameToId.get(agentName) : undefined;
      return { ...base, type: 'AGENT_METADATA', agentId, content: labels.planUpdate };
    }

    // Agent error
    if (evType === 'agent_error') {
      const agentName: string = data.agent || '';
      const kind: string = data.kind || '';
      const errText: string = String(data.error || data.message || '').slice(0, 400);
      const agentLabel = getDisplayAgentName(agentName);
      const kindLabel = kind === 'llm_call'
        ? labels.llmCallError
        : kind === 'parse'
          ? labels.llmParseError
          : kind === 'offline'
            ? labels.agentOffline
            : labels.agentError;
      const baseLabel = isZh() ? `智能体「${agentLabel}」${kindLabel}` : `Agent "${agentLabel}" ${kindLabel}`;
      const label = baseLabel + (errText ? pickText(`: ${errText}`, `：${errText}`) : '');
      return { ...base, type: 'SYSTEM', content: label };
    }

    if (evType === 'run_failed' || evType === 'error') {
      const errText = String(data.message || data.error || data.detail || '').trim();
      const sceneType = String(data.scene_type || data.sceneType || '').trim();
      const prefix = sceneType ? `${labels.runtimeFailed} (${sceneType})` : labels.runtimeFailed;
      return {
        ...base,
        type: 'SYSTEM',
        content: errText ? `${prefix}: ${errText}` : prefix,
      };
    }

    if (evType === 'cascade_distortion') {
      const agentName: string = data.agent || '';
      const displayAgentName = getDisplayAgentName(agentName);
      const tier: string = data.tier || '';
      const blocked = Boolean(data.blocked);
      const changed = data.changed !== false;
      const originalMessage = String(data.original_message || '').trim() || pickText('(empty)', '（空）');
      const draftMessage = String(data.agent_draft_message || '').trim();
      const finalMessage = String(data.final_message || '').trim() || pickText('(blocked / no downstream message)', '（已截留 / 无下传内容）');
      const reason = String(data.reason || '').trim() || pickText('No reason provided', '未提供原因');
      const metrics = `${pickText('strength', '失真强度')}=${data.distortion_strength ?? '-'}, `
        + `${pickText('conflict', '冲突敏感度')}=${data.conflict_sensitivity ?? '-'}, `
        + `${pickText('block', '阻断概率')}=${data.block_probability ?? '-'}, `
        + `${pickText('pressure', '冲突压力')}=${data.pressure ?? '-'}, `
        + `${pickText('tendency', '截留倾向')}=${data.block_tendency ?? '-'}`;
      const title = blocked ? labels.distortionBlocked : changed ? labels.distortionAdjusted : labels.distortionUnchanged;
      const reasonLine = blocked || changed
        ? `${labels.distortedReason}: ${reason}`
        : `${labels.pressureReason}: ${reason}`;
      const agentLabel = displayAgentName ? `${displayAgentName}${tier ? ` (${tier})` : ''}` : '';
      const content = [
        agentLabel ? `${agentLabel} - ${title}` : title,
        `${labels.originalMessage}: ${originalMessage}`,
        draftMessage ? `${labels.draftMessage}: ${draftMessage}` : '',
        `${labels.finalMessage}: ${finalMessage}`,
        reasonLine,
        `${labels.metricsLabel}: ${metrics}`,
      ].filter(Boolean).join('\n');
      return {
        ...base,
        type: 'SYSTEM',
        content,
        structuredData: {
          kind: 'policy_diff',
          title,
          agentLabel,
          leftTitle: labels.originalMessage,
          leftContent: originalMessage,
          draftTitle: draftMessage ? labels.draftMessage : undefined,
          draftContent: draftMessage || undefined,
          rightTitle: labels.finalMessage,
          rightContent: finalMessage,
          reasonLabel: blocked || changed ? labels.distortedReason : labels.pressureReason,
          reason,
          metricsLabel: labels.metricsLabel,
          metrics,
        },
      };
    }

    if (evType === 'cascade_input_classified') {
      const entered = Boolean(data.entered_distortion_chain);
      const content = String(data.content || '').trim();
      const label = entered ? labels.distortionInput : labels.nonDistortionInput;
      return {
        ...base,
        type: 'ENVIRONMENT',
        content: content ? `${label}\n${content}` : label,
      };
    }

    if (evType === 'private_cascade_input') {
      const visibleTo = String(data.visible_to || '').trim();
      const content = String(data.content || '').trim();
      const label = visibleTo
        ? `${labels.privateCascadeInput} ${visibleTo} ${labels.waitingForTopTier}`
        : `${labels.privateCascadeInput} ? ${labels.waitingForTopTier}`;
      return {
        ...base,
        type: 'ENVIRONMENT',
        content: content ? `${label}\n${content}` : label,
      };
    }

    // Public broadcast / environment event
    if (evType === 'system_broadcast' || evType === 'public_event') {
      const text = data.text || data.message || JSON.stringify(ev);
      const senderName: string = data.sender || '';
      const eventType: string = data.type || '';
      const recipients = Array.isArray(data.recipients)
        ? data.recipients.map((value: unknown) => String(value || '').trim()).filter(Boolean)
        : [];
      const scoped = Boolean(data.scoped);

      if (eventType === 'TalkToEvent' && senderName) {
        const agentId = senderName ? nameToId.get(senderName) : undefined;
        return { ...base, type: 'AGENT_SAY', agentId, content: text };
      }

      const talkToMatch = text.match(/^\[[^\]]+\]\s*([^t]+?)\s+to\s+([^:]+?):\s*(.+)$/);
      if (talkToMatch) {
        const talkToSender = talkToMatch[1].trim();
        const agentId = talkToSender ? nameToId.get(talkToSender) : undefined;
        if (agentId) return { ...base, type: 'AGENT_SAY', agentId, content: text };
      }

      const isMessageEvent = eventType === 'MessageEvent' || /\[(Message|消息)\]\s*[^:]+:/.test(text);
      if (isMessageEvent && senderName) {
        const agentId = senderName ? nameToId.get(senderName) : undefined;
        return { ...base, type: 'AGENT_SAY', agentId, content: text };
      }

      const scopeLabel = scoped ? labels.privateBroadcast : labels.globalBroadcast;
      const recipientText = recipients.length > 0 ? recipients.join(', ') : labels.allAgents;
      const content = [
        scopeLabel,
        `${labels.recipientsLabel}: ${recipientText}`,
        text,
      ].join('\n');
      return { ...base, type: 'ENVIRONMENT', content };
    }

    // Action end
    if (evType === 'action_end') {
      const actorName: string = data.actor || data.agent || data.name || '';
      const actionData = data.action || {};

      // Handle nested action structure from legacy agent responses
      // Legacy format: {thoughts, response, action: {name, parameters}, context_update, metadata}
      // Direct format: {name, parameters}
      let actionName: string = '';
      if (actionData.action && typeof actionData.action === 'object') {
        actionName = actionData.action.name || '';
      } else if (actionData.name) {
        actionName = actionData.name;
      } else if (typeof actionData.action === 'string') {
        actionName = actionData.action;
      }

      const agentId = actorName ? nameToId.get(actorName) : undefined;
      const displayAgentName = getDisplayAgentName(actorName);
      const isSpeech = actionName === 'send_message' || actionName === 'say';

      if (isSpeech) return null;

      const readableAction = translateActionName(actionName);
      const label = `${displayAgentName} ${labels.actionEnd} ${readableAction}`;
      return { ...base, type: 'AGENT_ACTION', agentId, content: label, actionLabel: readableAction };
    }

    // Experiment action - clean format from the new experiment system
    if (evType === 'experiment_action') {
      const agentName: string = data.agent || '';
      const actionName: string = data.action || '';
      const parameters = data.parameters || {};
      const summary: string = data.summary || '';
      const narrativeText = String(data.text || '').trim();
      const payoff = data.payoff;
      const round: number = data.round || 0;
      const skipped: boolean = data.skipped || false;
      const agentId = agentName ? nameToId.get(agentName) : undefined;
      const displayAgentName = getDisplayAgentName(agentName);

      // Build readable label
      const readableAction = translateActionName(actionName);
      const o: Record<string, number> = {};
      if (typeof payoff === 'number') {
        o.payoff = payoff;
      }
      Object.entries(parameters).forEach(([k, v]) => {
        if (typeof v === 'number') {
          o[k] = v;
        }
      });
      const outcomeData: Record<string, number> | undefined =
        Object.keys(o).length > 0 ? o : undefined;

      // Use summary if available (it contains action result info)
      if (summary) {
        const narrativeContent = formatExperimentNarrative(displayAgentName, narrativeText);
        const contentBase = narrativeContent
          ? narrativeContent
          : summary;
        const content = payoff !== null && payoff !== undefined
          ? `${contentBase}${pickText(` -> payoff=${payoff}`, ` -> 收益=${payoff}`)}`
          : contentBase;
        return { ...base, type: 'AGENT_ACTION', agentId, content, actionLabel: readableAction, outcome: outcomeData };
      }

      // Otherwise build our own label
      let label: string;
      if (skipped) {
        label = pickText(
          `Round ${round}: ${displayAgentName} - skipped turn`,
          `第${round}轮: ${displayAgentName} - 跳过回合`
        );
      } else {
        label = pickText(
          `Round ${round}: ${displayAgentName} chose ${readableAction}`,
          `第${round}轮: ${displayAgentName}选择了${readableAction}`
        );
      }

      // Add parameters if any meaningful ones exist
      if (parameters && Object.keys(parameters).length > 0) {
        const meaningfulParams = formatExperimentParameters(parameters);
        if (meaningfulParams) {
          label += ` (${meaningfulParams})`;
        }
      }

      if (payoff !== null && payoff !== undefined) {
        label += pickText(` -> payoff=${payoff}`, ` -> 收益=${payoff}`);
      }

      return { ...base, type: 'AGENT_ACTION', agentId, content: label, actionLabel: readableAction, outcome: outcomeData };
    }

    if (evType === 'experiment_response') {
      const agentName: string = data.agent || '';
      const actionName: string = data.action || '';
      const response = String(data.response || data.message || '').trim();
      const reason = String(data.reason || '').trim();
      const agentId = agentName ? nameToId.get(agentName) : undefined;
      const readableAction = translateActionName(actionName);

      const lines = [];
      if (response) {
        lines.push(response);
      }
      if (reason) {
        lines.push(pickText(
          `Why this action: ${reason}`,
          `选择“${readableAction}”的原因：${reason}`
        ));
      } else if (readableAction) {
        lines.push(pickText(
          `Chosen action: ${readableAction}`,
          `关联动作：${readableAction}`
        ));
      }

      const content = lines.filter(Boolean).join('\n');
      if (!content) return null;
      return { ...base, type: 'AGENT_SAY', agentId, content };
    }

    // Reduction action — PGG deduction events emitted by the reduce handler
    if (evType === 'reduction_action') {
      const agentName: string = data.reducer || '';
      const targetName: string = data.target || '';
      const amount: number = data.amount || 0;
      const deduction: number = data.deduction || 0;
      const agentId = agentName ? nameToId.get(agentName) : undefined;
      const displayAgentName = getDisplayAgentName(agentName);
      const displayTargetName = getDisplayAgentName(targetName);

      const content = pickText(
        `${displayAgentName} reduced ${displayTargetName} by ${amount} (deduction: ${deduction})`,
        `${displayAgentName} 对 ${displayTargetName} 施加了 ${amount} 点扣减（实际扣除: ${deduction}）`
      );
      return { ...base, type: 'AGENT_ACTION', agentId, content, actionLabel: translateActionName('reduce') };
    }

    const text = data.text || data.message || evType || labels.systemEvent;
    return { ...base, type: 'SYSTEM', content: text };
  }).filter((entry): entry is LogEntry => entry !== null);
};

// Default export for dynamic imports (used by tests)
export default {
  SYSTEM_TEMPLATES,
  addTime,
  formatWorldTime,
  generateNodes,
  mapGraphToNodes,
  generateAgentsWithAI,
  generateAgentsWithDemographics,
  mapBackendEventsToLogs,
  fetchEnvironmentSuggestions
};

export {
  SYSTEM_TEMPLATES,
  generateAgentsWithAI,
  generateAgentsWithDemographics,
  fetchEnvironmentSuggestions,
};
