import { apiClient } from './client';

export interface DataSource {
  id: string;
  name: string;
  api_url: string;
  auth_type: 'none' | 'bearer' | 'api_key';
  auth_token?: string;
  poll_interval_seconds: number;
  event_type: string;
  is_global: boolean;
  simulation_id: string | null;
  field_mapping: Record<string, string>;
  is_enabled: boolean;
  last_poll_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export const dataSourceApi = {
  list: (simulationId?: string) =>
    apiClient.get('/data-sources', { params: simulationId ? { simulation_id: simulationId } : undefined }),

  create: (data: Partial<DataSource>) =>
    apiClient.post('/data-sources', data),

  update: (id: string, data: Partial<DataSource>) =>
    apiClient.put(`/data-sources/${id}`, data),

  delete: (id: string) =>
    apiClient.delete(`/data-sources/${id}`),

  test: (id: string) =>
    apiClient.post(`/data-sources/${id}/test`),

  poll: (id: string) =>
    apiClient.post(`/data-sources/${id}/poll`),

  getStatus: (id: string) =>
    apiClient.get(`/data-sources/${id}/status`),
};