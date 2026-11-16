// frontend/store/llmConsoleSlice.ts
// LLM 控制台的状态管理切片
import { StateCreator } from "zustand";
import type { ModelRecord } from "../services/models";
import type { Provider } from "../services/providers";

export type LlmConsoleState = {
  // 全局状态
  providers: Provider[];
  models: ModelRecord[];
  
  // UI状态
  selectedProviderId: number | null;
  selectedModelId: string | null;
  activeTestModelId: string | null;
  
  // 编辑/创建状态
  isProviderFormOpen: boolean;
  isModelEditorOpen: boolean;
  editingProviderId: number | null;
  editingModelId: string | null;
  isBatchImportOpen: boolean;
  
  // 测试台状态
  testInput: {
    systemPrompt: string;
    userPrompt: string;
    temperature: number;
    maxTokens: number;
    responseFormat: "text" | "json";
  };
  testResult: {
    status: "idle" | "loading" | "success" | "error";
    responseTime: number;
    tokensUsed?: { prompt: number; completion: number };
    content?: string;
    errorMessage?: string;
  };
  
  // 列表过滤
  modelSearch: string;
  modelProviderFilter: number | null;
  modelCapabilityFilter: string[];
  onlyEnabledModels: boolean;
  
  // Action方法
  setProviders: (providers: Provider[]) => void;
  setModels: (models: ModelRecord[]) => void;
  setSelectedProvider: (id: number | null) => void;
  setSelectedModel: (id: string | null) => void;
  setActiveTestModel: (id: string | null) => void;
  
  openProviderForm: (id?: number) => void;
  closeProviderForm: () => void;
  openModelEditor: (id?: string) => void;
  closeModelEditor: () => void;
  openBatchImport: () => void;
  closeBatchImport: () => void;
  
  setTestInput: (input: Partial<LlmConsoleState["testInput"]>) => void;
  setTestResult: (result: Partial<LlmConsoleState["testResult"]>) => void;
  
  setModelSearch: (query: string) => void;
  setModelProviderFilter: (id: number | null) => void;
  setModelCapabilityFilter: (capabilities: string[]) => void;
  setOnlyEnabledModels: (enabled: boolean) => void;
};

const initialTestInput = {
  systemPrompt: "You are a helpful AI assistant.",
  userPrompt: "",
  temperature: 0.7,
  maxTokens: 1000,
  responseFormat: "text" as const,
};

const initialTestResult = {
  status: "idle" as const,
  responseTime: 0,
};

export const createLlmConsoleSlice: StateCreator<LlmConsoleState> = (set) => ({
  providers: [],
  models: [],
  selectedProviderId: null,
  selectedModelId: null,
  activeTestModelId: null,
  
  isProviderFormOpen: false,
  isModelEditorOpen: false,
  editingProviderId: null,
  editingModelId: null,
  isBatchImportOpen: false,
  
  testInput: initialTestInput,
  testResult: initialTestResult,
  
  modelSearch: "",
  modelProviderFilter: null,
  modelCapabilityFilter: [],
  onlyEnabledModels: true,
  
  setProviders: (providers) => set({ providers }),
  setModels: (models) => set({ models }),
  setSelectedProvider: (id) => set({ selectedProviderId: id }),
  setSelectedModel: (id) => set({ selectedModelId: id }),
  setActiveTestModel: (id) => set({ activeTestModelId: id }),
  
  openProviderForm: (id) => 
    set({ isProviderFormOpen: true, editingProviderId: id ?? null }),
  closeProviderForm: () => 
    set({ isProviderFormOpen: false, editingProviderId: null }),
  openModelEditor: (id) => 
    set({ isModelEditorOpen: true, editingModelId: id ?? null }),
  closeModelEditor: () => 
    set({ isModelEditorOpen: false, editingModelId: null }),
  openBatchImport: () => 
    set({ isBatchImportOpen: true }),
  closeBatchImport: () => 
    set({ isBatchImportOpen: false }),
  
  setTestInput: (input) => 
    set((state) => ({ testInput: { ...state.testInput, ...input } })),
  setTestResult: (result) => 
    set((state) => ({ testResult: { ...state.testResult, ...result } })),
  
  setModelSearch: (query) => set({ modelSearch: query }),
  setModelProviderFilter: (id) => set({ modelProviderFilter: id }),
  setModelCapabilityFilter: (caps) => set({ modelCapabilityFilter: caps }),
  setOnlyEnabledModels: (enabled) => set({ onlyEnabledModels: enabled }),
});
