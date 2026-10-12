/*
This file turns saved agent history into simple result data.
listMetrics looks through every agent and returns all metric names in sorted order.
computeMetricTrajectories builds one value series per agent for one chosen metric.
computeMetricAggregate combines many agent series into one mean line with min and max bounds.
computeEventCountByAgent counts how many saved events belong to each agent.
computeEventCountByRound counts how many saved events happened in each round.
*/

import type { Agent, LogEntry, SimNode } from '@/types';

export type Series = { agentId: string; agentName: string; values: number[] };
export type MetricAggregatePoint = { round: number; mean: number; min: number; max: number };
export type VariantAggregate = { variantName: string; points: MetricAggregatePoint[] };
export type AgentCount = { agentId: string; count: number };
export type RoundCount = { round: number; count: number };

export function filterLogsToSelectedBranch(
  logs: LogEntry[],
  nodes: SimNode[],
  selectedNodeId: string | null | undefined,
): LogEntry[] {
  if (!Array.isArray(logs)) {
    throw new Error('filterLogsToSelectedBranch: logs must be an array');
  }

  if (!selectedNodeId || !Array.isArray(nodes) || nodes.length === 0) {
    return logs;
  }

  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  if (!nodesById.has(selectedNodeId)) {
    return logs;
  }

  const branchIds = new Set<string>();
  let currentId: string | null | undefined = selectedNodeId;

  while (currentId) {
    const currentNode = nodesById.get(currentId);
    if (!currentNode || branchIds.has(currentNode.id)) {
      break;
    }
    branchIds.add(currentNode.id);
    currentId = currentNode.parentId;
  }

  return logs.filter(
    (log) => !log.nodeId || !nodesById.has(log.nodeId) || branchIds.has(log.nodeId),
  );
}

export function listMetrics(agents: Agent[]): string[] {
  if (!Array.isArray(agents)) {
    throw new Error('listMetrics: agents must be an array');
  }

  const metrics = new Set<string>();

  for (const agent of agents) {
    for (const metric of Object.keys(agent.history)) {
      metrics.add(metric);
    }
  }

  return Array.from(metrics).sort();
}

export function computeMetricTrajectories(agents: Agent[], metric: string): Series[] {
  if (typeof metric !== 'string' || metric.length === 0) {
    throw new Error('computeMetricTrajectories: metric must be a non-empty string');
  }

  const series = agents
    .filter((agent) => Object.prototype.hasOwnProperty.call(agent.history, metric))
    .map((agent) => ({
      agentId: agent.id,
      agentName: agent.name,
      values: agent.history[metric],
    }))
    .sort((left, right) => left.agentName.localeCompare(right.agentName));

  if (series.length === 0) {
    throw new Error(`computeMetricTrajectories: metric "${metric}" not found in any agent history`);
  }

  return series;
}

export function computeMetricAggregate(series: Series[]): MetricAggregatePoint[] {
  if (!Array.isArray(series) || series.length === 0) {
    throw new Error('computeMetricAggregate: series must be a non-empty array');
  }

  const maxLen = Math.max(...series.map((s) => s.values.length));
  if (maxLen === 0) {
    throw new Error('computeMetricAggregate: series have no values');
  }

  const points: MetricAggregatePoint[] = [];

  for (let i = 0; i < maxLen; i++) {
    const vals: number[] = [];

    for (const s of series) {
      if (i < s.values.length) {
        vals.push(s.values[i]);
      }
    }

    const sum = vals.reduce((acc, v) => acc + v, 0);
    points.push({
      round: i + 1,
      mean: sum / vals.length,
      min: Math.min(...vals),
      max: Math.max(...vals),
    });
  }

  return points;
}

export function computeEventCountByAgent(logs: LogEntry[]): AgentCount[] {
  if (!Array.isArray(logs)) {
    throw new Error('computeEventCountByAgent: logs must be an array');
  }

  const counts = new Map<string, number>();

  for (const log of logs) {
    if (typeof log.agentId === 'string' && log.agentId.length > 0) {
      const currentCount = counts.get(log.agentId);
      if (currentCount === undefined) {
        counts.set(log.agentId, 1);
        continue;
      }

      counts.set(log.agentId, currentCount + 1);
    }
  }

  return Array.from(counts.entries())
    .map(([agentId, count]) => ({ agentId, count }))
    .sort((left, right) => {
      if (left.count !== right.count) {
        return right.count - left.count;
      }

      return left.agentId.localeCompare(right.agentId);
    });
}

export function computeEventCountByRound(logs: LogEntry[]): RoundCount[] {
  if (!Array.isArray(logs)) {
    throw new Error('computeEventCountByRound: logs must be an array');
  }

  const counts = new Map<number, number>();

  for (const log of logs) {
    const currentCount = counts.get(log.round);
    if (currentCount === undefined) {
      counts.set(log.round, 1);
      continue;
    }

    counts.set(log.round, currentCount + 1);
  }

  return Array.from(counts.entries())
    .map(([round, count]) => ({ round, count }))
    .sort((left, right) => left.round - right.round);
}

export function hydrateAgentHistoryFromLogs(logs: LogEntry[], agents: Agent[]): Agent[] {
  if (!Array.isArray(logs)) {
    throw new Error('hydrateAgentHistoryFromLogs: logs must be an array');
  }

  if (!Array.isArray(agents)) {
    throw new Error('hydrateAgentHistoryFromLogs: agents must be an array');
  }

  const actionLogs = logs.filter(
    (log) =>
      log.type === 'AGENT_ACTION'
      && typeof log.agentId === 'string'
      && log.agentId.length > 0
      && log.outcome !== undefined
      && Object.keys(log.outcome).length > 0,
  );

  if (actionLogs.length === 0) {
    return agents;
  }

  const maxRound = Math.max(...actionLogs.map((log) => log.round));
  const store = new Map<string, Map<string, Map<number, number>>>();

  for (const log of actionLogs) {
    const agentId = log.agentId as string;

    if (!store.has(agentId)) {
      store.set(agentId, new Map());
    }

    const agentMetrics = store.get(agentId) as Map<string, Map<number, number>>;

    for (const [metric, value] of Object.entries(log.outcome as Record<string, number>)) {
      if (!agentMetrics.has(metric)) {
        agentMetrics.set(metric, new Map());
      }

      const roundsByMetric = agentMetrics.get(metric) as Map<number, number>;
      roundsByMetric.set(log.round, value);
    }
  }

  return agents.map((agent) => {
    const agentMetrics = store.get(agent.id);

    if (agentMetrics === undefined) {
      return agent;
    }

    const newHistory = { ...agent.history };

    agentMetrics.forEach((roundsByMetric, metric) => {
      if (newHistory[metric] !== undefined && newHistory[metric].length > 0) {
        return;
      }

      newHistory[metric] = Array.from({ length: maxRound }, (_, index) => {
        const value = roundsByMetric.get(index + 1);
        return typeof value === 'number' ? value : 0;
      });
    });

    return { ...agent, history: newHistory };
  });
}

export function computeMultiVariantAggregate(
  seriesByVariant: Record<string, Series[]>
): VariantAggregate[] {
  return Object.entries(seriesByVariant).map(([variantName, series]) => ({
    variantName,
    points: computeMetricAggregate(series),
  }));
}
