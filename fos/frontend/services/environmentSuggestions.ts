import { apiClient } from './client';

export interface EnvironmentSuggestion {
  event_type: string;
  description: string;
  severity: string;
  notice_only?: boolean;
  receivers?: string[];
  node_id?: string | number;
}

export interface SuggestionStatus {
  available: boolean;
  turn: number | null;
  enabled?: boolean;
}

export async function getSuggestionStatus(simulationId: string, nodeId?: string | number | null): Promise<SuggestionStatus> {
  const suffix = nodeId != null ? `?node_id=${encodeURIComponent(String(nodeId))}` : '';
  const response = await apiClient.get(`/simulations/${simulationId}/suggestions/status${suffix}`);
  return response.data;
}

export async function generateSuggestions(simulationId: string, nodeId?: string | number | null): Promise<{ suggestions: EnvironmentSuggestion[] }> {
  const suffix = nodeId != null ? `?node_id=${encodeURIComponent(String(nodeId))}` : '';
  const response = await apiClient.post(`/simulations/${simulationId}/suggestions/generate${suffix}`);
  return response.data;
}

export async function applyEnvironmentEvent(
  simulationId: string,
  event: EnvironmentSuggestion,
): Promise<{ success: boolean; message: string }> {
  const response = await apiClient.post(`/simulations/${simulationId}/events/environment`, event);
  return response.data;
}

export async function dismissSuggestions(simulationId: string): Promise<{ success: boolean; message: string }> {
  const response = await apiClient.post(`/simulations/${simulationId}/suggestions/dismiss`);
  return response.data;
}
