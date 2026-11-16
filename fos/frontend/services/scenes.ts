import { apiClient } from "./client";

export type SceneOption = {
  type: string;
  name: string;
  description?: string;
  config_schema: Record<string, unknown>;
  allowed_actions?: string[];
  basic_actions?: string[];
};

export async function listScenes(): Promise<SceneOption[]> {
  const { data } = await apiClient.get<SceneOption[]>("scenes");
  return data;
}
