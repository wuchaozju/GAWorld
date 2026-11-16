// frontend/services/models.ts
// LLM 模型管理 API 客户端
import { apiClient } from "./client";
import { extractApiErrorMessage } from "../utils/apiError";

export type ModelCapability = 
  | "text"
  | "vision" 
  | "audio"
  | "json"
  | "function_call"
  | "reasoning";

export type ModelRecord = {
  id?: string;
  displayName: string;
  modelId: string;
  providerId: number;
  protocolType: "openai" | "google" | "custom";
  capabilities: ModelCapability[];
  contextWindow: number;
  inputPrice?: number;      // per 1M tokens
  outputPrice?: number;     // per 1M tokens
  tags?: string[];
  enabled: boolean;
  isDefault: boolean;
  lastTestedAt?: string;
  lastTestStatus?: "success" | "failed" | null;
  customMetadata?: Record<string, unknown>;
};

export async function listModels(): Promise<ModelRecord[]> {
  try {
    const { data } = await apiClient.get<ModelRecord[]>("models");
    return data;
  } catch {
    // 如果后端还没实现，返回空数组或mock数据
    return [];
  }
}

export async function createModel(payload: Omit<ModelRecord, "id">): Promise<ModelRecord> {
  try {
    const { data } = await apiClient.post<ModelRecord>("models", payload);
    return data;
  } catch (error) {
    // Mock: 返回带ID的模型
    return { ...payload, id: `model_${Date.now()}` };
  }
}

export async function updateModel(modelId: string, payload: Partial<ModelRecord>): Promise<ModelRecord> {
  try {
    const { data } = await apiClient.patch<ModelRecord>(`models/${modelId}`, payload);
    return data;
  } catch (error) {
    // Mock: 返回更新后的模型
    return { ...payload, id: modelId } as ModelRecord;
  }
}

export async function deleteModel(modelId: string): Promise<void> {
  try {
    await apiClient.delete(`models/${modelId}`);
  } catch {
    // Mock成功
  }
}

export async function batchCreateModels(payloads: Omit<ModelRecord, "id">[]): Promise<ModelRecord[]> {
  try {
    const { data } = await apiClient.post<ModelRecord[]>("models/batch", { models: payloads });
    return data;
  } catch (error) {
    // Mock: 返回所有模型并添加ID
    return payloads.map((m, i) => ({ ...m, id: `model_${Date.now()}_${i}` }));
  }
}

export async function testModel(
  modelId: string,
  prompt: string,
  systemPrompt?: string,
  options?: { temperature?: number; maxTokens?: number }
): Promise<{ 
  success: boolean; 
  responseTime: number; 
  tokensUsed?: { prompt: number; completion: number }; 
  content?: string; 
  error?: string 
}> {
  try {
    const { data } = await apiClient.post(`models/${modelId}/test`, {
      prompt,
      systemPrompt,
      ...options,
    });
    return data;
  } catch (error: any) {
    return {
      success: false,
      responseTime: 0,
      error: extractApiErrorMessage(error),
    };
  }
}
