import { apiClient } from "./client";

export type SearchProvider = {
  id: number;
  provider: string;
  base_url: string | null;
  has_api_key: boolean;
  config?: Record<string, unknown> | null;
};

export async function listSearchProviders(): Promise<SearchProvider[]> {
  const { data } = await apiClient.get<SearchProvider[]>("search-providers");
  return data;
}

export async function createSearchProvider(payload: {
  provider: string;
  base_url?: string | null;
  api_key?: string | null;
  config?: Record<string, unknown> | null;
}): Promise<SearchProvider> {
  const { data } = await apiClient.post<SearchProvider>("search-providers", payload);
  return data;
}

export async function updateSearchProvider(providerId: number, payload: {
  provider?: string;
  base_url?: string | null;
  api_key?: string | null;
  config?: Record<string, unknown> | null;
}): Promise<SearchProvider> {
  const { data } = await apiClient.patch<SearchProvider>(`search-providers/${providerId}`, payload);
  return data;
}
