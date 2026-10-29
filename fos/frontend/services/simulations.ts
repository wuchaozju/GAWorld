// frontend/api/simulations.ts

// 这一部分：给「旧前端」页面用（Dashboard / SavedSimulations 等）
// 使用 axios backendClient，走后端 /api/simulations 这些接口
import { apiClient } from "./backendClient";
export type { Simulation } from "../types";

// 列表类型可以先用 any，后面你想再加类型也可以
export async function listSimulations(): Promise<any[]> {
  const { data } = await apiClient.get("/simulations");
  return data;
}

export const getSimulations = listSimulations;

export async function deleteSimulation(simulationId: string): Promise<void> {
  await apiClient.delete(`/simulations/${simulationId}`);
}

export async function copySimulation(simulationId: string): Promise<any> {
  const { data } = await apiClient.post(
    `/simulations/${simulationId}/copy`,
    {}
  );
  return data;
}

export async function resumeSimulation(simulationId: string): Promise<any> {
  const { data } = await apiClient.post(
    `/simulations/${simulationId}/resume`,
    {}
  );
  return data;
}

export async function resetSimulation(simulationId: string): Promise<void> {
  await apiClient.post(`/simulations/${simulationId}/reset`, {});
}

export interface SimulationSnapshotItem {
  id: number;
  label: string;
  turns: number;
  state: Record<string, any>;
  created_at: string;
}

export async function listSimulationSnapshots(simulationId: string): Promise<SimulationSnapshotItem[]> {
  const { data } = await apiClient.get(`/simulations/${simulationId}/snapshots`);
  return data;
}

export async function createSimulationSnapshot(simulationId: string, label?: string): Promise<SimulationSnapshotItem> {
  const { data } = await apiClient.post(`/simulations/${simulationId}/save`, { label: label || '' });
  return data;
}

export async function resumeSimulationFromSnapshot(simulationId: string, snapshotId: number): Promise<any> {
  const { data } = await apiClient.post(`/simulations/${simulationId}/resume`, null, {
    params: { snapshot_id: snapshotId },
  });
  return data;
}

// Fetch a single simulation by id
export async function getSimulation(simulationId: string): Promise<any> {
  const { data } = await apiClient.get(`/simulations/${encodeURIComponent(simulationId)}`);
  return data;
}

// 一般用于给仿真改名 / 保存状态之类
export async function saveSimulation(
  simulationId: string,
  payload: { name?: string; [key: string]: any } = {}
): Promise<any> {
  const { data } = await apiClient.post(
    `/simulations/${simulationId}/save`,
    payload
  );
  return data;
}

// Update an existing simulation (patch)
export async function updateSimulation(
  simulationId: string,
  payload: { name?: string; [key: string]: any } = {}
): Promise<any> {
  const { data } = await apiClient.patch(`/simulations/${encodeURIComponent(simulationId)}`, payload);
  return data;
}

export async function enqueueSync(simulationId: string | null, payload: any): Promise<any> {
  const id = simulationId ? encodeURIComponent(simulationId) : '';
  const { data } = await apiClient.post(`/simulations/${id}/sync`, payload || {});
  return data;
}

export async function getSyncLog(simulationId: string | null, syncLogId: number): Promise<any> {
  const id = simulationId ? encodeURIComponent(simulationId) : '';
  const { data } = await apiClient.get(`/simulations/${id}/sync/${syncLogId}`);
  return data;
}

// ---------------------------------------------------------
// 这一部分：给「新前端 / SimTree」用（store.ts 里的 createSimulationApi / startSimulation）
// 注意：这里保留 base / token 参数以兼容调用方，但**不再使用**，统一走 apiClient，
// 这样就会自动带上登录 Cookie / Bearer Token，不会再 401。
// ---------------------------------------------------------

type CreateSimulationPayload = any;

// 创建仿真（connected 模式用）
export async function createSimulation(
  base: string, // 兼容旧签名，实际不再使用
  payload: CreateSimulationPayload,
  token?: string // 兼容旧签名，实际不再使用
): Promise<any> {
  const { data } = await apiClient.post("/simulations", payload);
  return data;
}

// 启动仿真（connected 模式用）
export async function startSimulation(
  base: string, // 兼容旧签名，实际不再使用
  simulationId: string,
  token?: string // 兼容旧签名，实际不再使用
): Promise<any> {
  const { data } = await apiClient.post(
    `/simulations/${encodeURIComponent(simulationId)}/start`,
    {}
  );
  return data;
}

// ---------------------------------------------------------
// Document Upload API (Per-Agent Private Knowledge)
// ---------------------------------------------------------

export interface DocumentInfo {
  id: string;
  filename: string;
  file_size: number;
  uploaded_at: string;
  chunks_count: number;
}

export interface UploadDocumentResponse {
  success: boolean;
  doc_id: string;
  chunks_count: number;
  agent_name: string;
  filename: string;
}

// Upload a document to an agent's private knowledge base
export async function uploadAgentDocument(
  simulationId: string,
  agentName: string,
  file: File
): Promise<UploadDocumentResponse> {
  const formData = new FormData();
  formData.append('data', file);

  const { data } = await apiClient.post(
    `/simulations/${encodeURIComponent(simulationId)}/agents/${encodeURIComponent(agentName)}/documents`,
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    }
  );
  return data;
}

// List documents for an agent
export async function listAgentDocuments(
  simulationId: string,
  agentName: string,
  nodeId?: string | number
): Promise<DocumentInfo[]> {
  let url = `/simulations/${encodeURIComponent(simulationId)}/agents/${encodeURIComponent(agentName)}/documents`;
  if (nodeId !== undefined && nodeId !== null) {
    url += `?node_id=${encodeURIComponent(String(nodeId))}`;
  }
  const { data } = await apiClient.get(url);
  return data;
}

// Delete a document from an agent
export async function deleteAgentDocument(
  simulationId: string,
  agentName: string,
  docId: string
): Promise<{ success: boolean; deleted_doc_id: string }> {
  const { data } = await apiClient.delete(
    `/simulations/${encodeURIComponent(simulationId)}/agents/${encodeURIComponent(agentName)}/documents/${encodeURIComponent(docId)}`
  );
  return data;
}

// ---------------------------------------------------------
// Global Knowledge Base API
// ---------------------------------------------------------

export interface GlobalKnowledgeItem {
  id: string;
  title: string;
  content_preview: string;
  source_type: 'manual_text' | 'document';
  filename: string | null;
  created_at: string;
  chunks_count: number;
}

export interface AddGlobalKnowledgeResponse {
  success: boolean;
  kw_id: string;
}

export interface UploadGlobalDocumentResponse {
  success: boolean;
  kw_id: string;
  chunks_count: number;
  filename: string;
}

// Add text content to global knowledge
export async function addGlobalKnowledge(
  simulationId: string,
  content: string,
  title?: string
): Promise<AddGlobalKnowledgeResponse> {
  const { data } = await apiClient.post(
    `/simulations/${encodeURIComponent(simulationId)}/global-knowledge`,
    { content, title: title || '' }
  );
  return data;
}

// Upload a document to global knowledge
export async function uploadGlobalDocument(
  simulationId: string,
  file: File
): Promise<UploadGlobalDocumentResponse> {
  const formData = new FormData();
  formData.append('data', file);

  const { data } = await apiClient.post(
    `/simulations/${encodeURIComponent(simulationId)}/global-knowledge/documents`,
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    }
  );
  return data;
}

// List global knowledge items
export async function listGlobalKnowledge(
  simulationId: string
): Promise<GlobalKnowledgeItem[]> {
  const { data } = await apiClient.get(
    `/simulations/${encodeURIComponent(simulationId)}/global-knowledge`
  );
  return data;
}

// Delete a global knowledge item
export async function deleteGlobalKnowledge(
  simulationId: string,
  kwId: string
): Promise<{ success: boolean; deleted_kw_id: string }> {
  const { data } = await apiClient.delete(
    `/simulations/${encodeURIComponent(simulationId)}/global-knowledge/${encodeURIComponent(kwId)}`
  );
  return data;
}

// ---------------------------------------------------------
// Agent LLM Config API
// ---------------------------------------------------------

export interface UpdateAgentLLMConfigRequest {
  agent_id: string;
  llm_config: {
    provider: string;
    model: string;
  };
  provider_id?: number | null;
}

export interface UpdateAgentLLMConfigResponse {
  message: string;
  agent_id: string;
  llm_config: {
    provider: string;
    model: string;
  };
  provider_id?: number | null;
}

// Update an agent's LLM configuration
export async function updateAgentLLMConfig(
  simulationId: string,
  agentId: string,
  llmConfig: { provider: string; model: string; provider_id?: number | null }
): Promise<UpdateAgentLLMConfigResponse> {
  const { data } = await apiClient.patch(
    `/simulations/${encodeURIComponent(simulationId)}/agents/llm-config`,
    {
      agent_id: agentId,
      llm_config: {
        provider: llmConfig.provider,
        model: llmConfig.model,
      },
      provider_id: llmConfig.provider_id,
    }
  );
  return data;
}