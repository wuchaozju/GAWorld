// frontend/api/providers.ts
import { apiClient } from "./client";

export type Provider = {
  id: number;
  name: string;
  provider: string;              // 比如 "openai-compatible" / "gemini"
  model: string;
  base_url: string | null;
  last_test_status?: string | null;
  last_tested_at?: string | null;
  has_api_key: boolean;
  config?: Record<string, unknown> | null;

  // 新增：如果后端有标记“当前/默认提供商”，就可以用上（没有也没关系）
  is_active?: boolean;
  is_default?: boolean;
};

export async function listProviders(): Promise<Provider[]> {
  const { data } = await apiClient.get<Provider[]>("providers");
  return data;
}

export async function createProvider(payload: {
  name: string;
  provider: string;
  model: string;
  base_url?: string | null;
  api_key?: string | null;
  config?: Record<string, unknown> | null;
}): Promise<Provider> {
  const { data } = await apiClient.post<Provider>("providers", payload);
  return data;
}

export async function testProvider(providerId: number): Promise<{ message: string }> {
  const { data } = await apiClient.post<{ message: string }>(`providers/${providerId}/test`);
  return data;
}

export async function updateProvider(providerId: number, payload: {
  name?: string;
  provider?: string;
  model?: string;
  base_url?: string | null;
  api_key?: string | null;
  config?: Record<string, unknown> | null;
}): Promise<Provider> {
  const { data } = await apiClient.patch<Provider>(`providers/${providerId}`, payload);
  return data;
}

export async function deleteProvider(providerId: number): Promise<void> {
  await apiClient.delete(`providers/${providerId}`);
}

export async function activateProvider(providerId: number): Promise<{ message: string }> {
  const { data } = await apiClient.post<{ message: string }>(`providers/${providerId}/activate`);
  return data;
}
