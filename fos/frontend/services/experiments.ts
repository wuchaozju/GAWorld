// frontend/services/experiments.ts
import { apiPost, apiGet } from './client';

export interface VariantSpec {
  name: string;
  ops: any[];
}

export interface LlmRoutingConfig {
  default: { provider: string; model: string } | null;
  agents?: Record<string, { provider: string; model: string }>;
  failure_policy?: 'pause_and_ask' | 'fail' | 'ordered_fallback';
  fallback_order?: string[];
}

export async function createExperiment(
  simulationId: string,
  name: string,
  baseNode: number,
  variants: VariantSpec[],
  llm?: LlmRoutingConfig,
) {
  const body: Record<string, unknown> = { name, base_node: baseNode, variants };
  if (llm) body.llm = llm;
  return apiPost<{ experiment_id: string }>(`/simulations/${simulationId}/experiments`, body);
}

export async function runExperiment(simulationId: string, experimentId: string, turns = 1) {
  const body = { turns };
  return apiPost<{ run_id: string }>(`/simulations/${simulationId}/experiments/${experimentId}/run`, body);
}

export async function listExperiments(simulationId: string) {
  return apiGet<{ experiments: any[] }>(`/simulations/${simulationId}/experiments`);
}

export async function getExperiment(simulationId: string, expId: string) {
  return apiGet<any>(`/simulations/${simulationId}/experiments/${expId}`);
}

export async function compareNodes(simulationId: string, nodeA: number, nodeB: number, use_llm = false, locale?: string) {
  return apiPost<any>(`/simulations/${simulationId}/compare`, { node_a: nodeA, node_b: nodeB, use_llm, locale });
}
