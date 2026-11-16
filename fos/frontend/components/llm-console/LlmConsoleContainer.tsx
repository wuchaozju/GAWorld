// frontend/components/llm-console/LlmConsoleContainer.tsx
import { useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  listProviders,
  testProvider as apiTestProvider,
  createProvider as apiCreateProvider,
  updateProvider as apiUpdateProvider,
  deleteProvider as apiDeleteProvider,
} from "../../services/providers";
import {
  listModels,
  createModel as apiCreateModel,
  updateModel as apiUpdateModel,
  deleteModel as apiDeleteModel,
  batchCreateModels,
  testModel as apiTestModel,
  type ModelRecord,
} from "../../services/models";
import type { Provider } from "../../services/providers";
import { useLlmConsoleStore } from "../../store/useLlmConsoleStore";
import { getBackendErrorDetail } from "../../utils/apiError";
import { StatusStrip } from "./StatusStrip";
import { ProviderPanel } from "./ProviderPanel";
import { ModelRegistryPanel } from "./ModelRegistryPanel";
import { TestConsolePanel } from "./TestConsolePanel";
import { ProviderFormModal } from "./ProviderFormModal";
import { BatchImportModal } from "./BatchImportModal";
import { ModelEditorDrawer } from "./ModelEditorDrawer";

export function LlmConsoleContainer() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  // 从Zustand store获取状态
  const {
    providers,
    models,
    selectedProviderId,
    selectedModelId,
    activeTestModelId,
    isProviderFormOpen,
    editingProviderId,
    isModelEditorOpen,
    editingModelId,
    isBatchImportOpen,
    modelSearch,
    modelProviderFilter,
    modelCapabilityFilter,
    onlyEnabledModels,
    testInput,
    testResult,
    setProviders,
    setModels,
    setSelectedProvider,
    setSelectedModel,
    setActiveTestModel,
    openProviderForm,
    closeProviderForm,
    openModelEditor,
    closeModelEditor,
    openBatchImport,
    closeBatchImport,
    setTestInput,
    setTestResult,
    setModelSearch,
    setModelProviderFilter,
    setModelCapabilityFilter,
    setOnlyEnabledModels,
  } = useLlmConsoleStore((state) => state);

  // 数据查询
  const providersQuery = useQuery({
    queryKey: ["providers"],
    queryFn: () => listProviders(),
  });

  const modelsQuery = useQuery({
    queryKey: ["models"],
    queryFn: () => listModels(),
  });

  // 同步远程数据到store
  useEffect(() => {
    if (providersQuery.data) {
      setProviders(providersQuery.data);
    }
  }, [providersQuery.data, setProviders]);

  useEffect(() => {
    if (modelsQuery.data) {
      setModels(modelsQuery.data);
    }
  }, [modelsQuery.data, setModels]);

  // 变更操作
  const createProviderMutation = useMutation({
    mutationFn: apiCreateProvider,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["providers"] }),
  });

  const updateProviderMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: any }) =>
      apiUpdateProvider(id, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["providers"] }),
  });

  const deleteProviderMutation = useMutation({
    mutationFn: apiDeleteProvider,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["providers"] }),
  });

  const testProviderMutation = useMutation({
    mutationFn: apiTestProvider,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["providers"] }),
  });

  const createModelMutation = useMutation({
    mutationFn: apiCreateModel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["models"] }),
  });

  const updateModelMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) =>
      apiUpdateModel(id, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["models"] }),
  });

  const deleteModelMutation = useMutation({
    mutationFn: apiDeleteModel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["models"] }),
  });

  const batchCreateModelsMutation = useMutation({
    mutationFn: batchCreateModels,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["models"] }),
  });

  const testModelMutation = useMutation({
    mutationFn: ({
      modelId,
      prompt,
      systemPrompt,
      options,
    }: {
      modelId: string;
      prompt: string;
      systemPrompt?: string;
      options?: any;
    }) => apiTestModel(modelId, prompt, systemPrompt, options),
    onSuccess: (data) => {
      const startTime = Date.now();
      const responseTime = Date.now() - startTime;
      setTestResult({
        status: data.success ? "success" : "error",
        responseTime: data.responseTime,
        tokensUsed: data.tokensUsed,
        content: data.content,
        errorMessage: data.error,
      });
    },
    onError: (error: any) => {
      const detail = getBackendErrorDetail(error);
      setTestResult({
        status: "error",
        responseTime: 0,
        errorMessage: detail !== null ? detail : t("components.llmConsole.testFailed"),
      });
    },
  });

  // 计算派生状态
  const activeProvider = useMemo(
    () =>
      selectedProviderId
        ? providers.find((p) => p.id === selectedProviderId)
        : providers.find((p) => p.is_active),
    [providers, selectedProviderId]
  );

  const activeModel = useMemo(
    () =>
      activeTestModelId
        ? models.find((m) => m.id === activeTestModelId)
        : models.find((m) => m.isDefault),
    [models, activeTestModelId]
  );

  const defaultModel = useMemo(
    () => models.find((m) => m.isDefault),
    [models]
  );

  const editingProvider = useMemo(
    () =>
      editingProviderId
        ? providers.find((p) => p.id === editingProviderId)
        : null,
    [providers, editingProviderId]
  );

  const editingModel = useMemo(
    () =>
      editingModelId ? models.find((m) => m.id === editingModelId) : null,
    [models, editingModelId]
  );

  // 处理函数
  const handleAddProvider = async (data: any) => {
    await createProviderMutation.mutateAsync(data);
  };

  const handleUpdateProvider = async (data: any) => {
    if (editingProviderId) {
      await updateProviderMutation.mutateAsync({ id: editingProviderId, data });
    }
  };

  const handleDeleteProvider = async (id: number) => {
    await deleteProviderMutation.mutateAsync(id);
  };

  const handleTestProvider = async (id: number) => {
    setTestResult({ status: "loading", responseTime: 0 });
    try {
      await testProviderMutation.mutateAsync(id);
      setTestResult({
        status: "success",
        responseTime: 100,
        content: t("components.llmConsole.connectionSuccessful"),
      });
    } catch (error: any) {
      const detail = getBackendErrorDetail(error);
      setTestResult({
        status: "error",
        responseTime: 0,
        errorMessage: detail !== null ? detail : t("components.llmConsole.connectionFailed"),
      });
    }
  };

  const handleAddModel = async (data: Omit<ModelRecord, "id">) => {
    await createModelMutation.mutateAsync(data);
  };

  const handleUpdateModel = async (data: Partial<ModelRecord>) => {
    if (editingModelId) {
      await updateModelMutation.mutateAsync({ id: editingModelId, data });
    }
  };

  const handleDeleteModel = async (id: string) => {
    await deleteModelMutation.mutateAsync(id);
  };

  const handleBatchImport = async (models: Omit<ModelRecord, "id">[]) => {
    await batchCreateModelsMutation.mutateAsync(models);
  };

  const handleTestModel = async () => {
    if (!activeModel) return;

    setTestResult({ status: "loading", responseTime: 0 });
    await testModelMutation.mutateAsync({
      modelId: activeModel.id || "",
      prompt: testInput.userPrompt,
      systemPrompt: testInput.systemPrompt,
      options: {
        temperature: testInput.temperature,
        maxTokens: testInput.maxTokens,
      },
    });
  };

  const handleExportModels = () => {
    const json = JSON.stringify(models, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `llm-models-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="llm-console-root">
      {/* 顶部状态条 */}
      <StatusStrip
        providers={providers}
        models={models}
        activeProvider={activeProvider}
        defaultModel={defaultModel}
        lastTestStatus={testResult.status as any}
        onAddProvider={() => openProviderForm()}
      />

      {/* 三栏工作台 */}
      <div className="llm-console-main">
        {/* 左侧：Provider 管理 */}
        <div className="llm-console-sidebar">
          <ProviderPanel
            providers={providers}
            selectedProviderId={selectedProviderId}
            onSelectProvider={setSelectedProvider}
            onEditProvider={(id) => openProviderForm(id)}
            onDeleteProvider={handleDeleteProvider}
            onTestProvider={handleTestProvider}
            onSetDefault={(id) =>
              updateProviderMutation.mutate({ id, data: { is_default: true } } as any)
            }
          />
        </div>

        {/* 中间：模型注册表 */}
        <div className="llm-console-main-area">
          <ModelRegistryPanel
            models={models}
            providers={providers}
            selectedModelId={selectedModelId}
            searchQuery={modelSearch}
            providerFilter={modelProviderFilter}
            capabilityFilter={modelCapabilityFilter}
            onlyEnabled={onlyEnabledModels}
            onSelectModel={setSelectedModel}
            onAddModel={() => openModelEditor()}
            onEditModel={(id) => openModelEditor(id)}
            onDeleteModel={handleDeleteModel}
            onDuplicateModel={(id) => {
              const model = models.find((m) => m.id === id);
              if (model) {
                const { id: _id, ...copy } = model;
                openModelEditor(id);
              }
            }}
            onSetDefault={(id) =>
              updateModelMutation.mutate({
                id,
                data: { isDefault: true },
              } as any)
            }
            onToggleEnabled={(id, enabled) =>
              updateModelMutation.mutate({
                id,
                data: { enabled },
              } as any)
            }
            onSearch={setModelSearch}
            onFilterProvider={setModelProviderFilter}
            onFilterCapabilities={setModelCapabilityFilter}
            onToggleOnlyEnabled={setOnlyEnabledModels}
            onBatchImport={openBatchImport}
            onExport={handleExportModels}
          />
        </div>

        {/* 右侧：测试台（固定） */}
        <div className="llm-console-test-panel">
          <TestConsolePanel
            providers={providers}
            models={models}
            activeModelId={activeTestModelId}
            testInput={testInput}
            testResult={testResult}
            onSetActiveModel={setActiveTestModel}
            onUpdateTestInput={setTestInput}
            onSendTest={handleTestModel}
            onClear={() => {
              setTestInput({ userPrompt: "" });
              setTestResult({ status: "idle", responseTime: 0 });
            }}
            onTestConnection={() => {
              if (activeProvider) {
                handleTestProvider(activeProvider.id);
              }
            }}
            isTestConnecting={testProviderMutation.isPending}
            isTestSending={testModelMutation.isPending}
          />
        </div>
      </div>

      {/* 模态框 */}
      <ProviderFormModal
        isOpen={isProviderFormOpen}
        editingProvider={editingProvider || null}
        onClose={closeProviderForm}
        onSubmit={
          editingProviderId ? handleUpdateProvider : handleAddProvider
        }
      />

      <ModelEditorDrawer
        isOpen={isModelEditorOpen}
        editingModel={editingModel || null}
        providers={providers}
        onClose={closeModelEditor}
        onSubmit={editingModelId ? handleUpdateModel : handleAddModel}
      />

      <BatchImportModal
        isOpen={isBatchImportOpen}
        providers={providers}
        onClose={closeBatchImport}
        onImport={handleBatchImport}
      />
    </div>
  );
}
