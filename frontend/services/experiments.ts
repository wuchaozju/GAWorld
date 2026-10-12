// frontend/services/experiments.ts
import { apiPost, apiGet } from './client';

export interface VariantSpec {
  name: string;
  ops: any[];
}

export async function createExperiment(simulationId: string, name: string, baseNode: number, variants: VariantSpec[]) {
  const body = { name, base_node: baseNode, variants };
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
