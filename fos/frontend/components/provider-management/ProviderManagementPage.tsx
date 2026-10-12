// frontend/components/provider-management/ProviderManagementPage.tsx
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ProviderPageHeader } from "./ProviderPageHeader";
import { ProviderCardList } from "./ProviderCardList";
import { ProviderDrawerForm } from "./ProviderDrawerForm";
import { DeleteProviderDialog } from "./DeleteProviderDialog";
import { ProviderEmptyState } from "./ProviderEmptyState";
import {
  activateProvider,
  createProvider,
  deleteProvider,
  listProviders,
  testProvider,
  updateProvider,
  type Provider,
} from "../../services/providers";

export type ProviderFormValues = {
  name: string;
  provider: "openai-compatible" | "custom";
  compatible_provider: "" | "chatgpt" | "deepseek" | "minimax" | "kimi";
  base_url: string;
  api_key: string;
  model: string;
  custom_endpoint: string;
  temperature: string;
  top_p: string;
  max_tokens: string;
  response_format: string;
  timeout_ms: string;
  metadata: string;
};

const EMPTY_FORM: ProviderFormValues = {
  name: "",
  provider: "openai-compatible",
  compatible_provider: "",
  base_url: "",
  api_key: "",
  model: "",
  custom_endpoint: "",
  temperature: "",
  top_p: "",
  max_tokens: "",
  response_format: "",
  timeout_ms: "",
  metadata: "",
};

const normalizeProviderType = (
  provider: string,
  config: Record<string, unknown>,
): ProviderFormValues["provider"] => {
  if (provider === "custom" || config["provider_type"] === "custom") return "custom";
  return "openai-compatible";
};

const normalizeCompatibleProvider = (
  provider: unknown,
): ProviderFormValues["compatible_provider"] => {
  if (provider === "chatgpt" || provider === "deepseek") return provider;
  if (provider === "minimax" || provider === "kimi") return provider;
  return "";
};

const formatDrawerValues = (provider: Provider | null): ProviderFormValues => {
  if (!provider) return EMPTY_FORM;

  const config = provider.config ?? {};
  return {
    name: provider.name ?? "",
    provider: normalizeProviderType(provider.provider, config),
    compatible_provider: normalizeCompatibleProvider(config["compatible_provider"]),
    base_url: provider.base_url ?? "",
    api_key: "",
    model: provider.model ?? "",
    custom_endpoint: String(config["custom_endpoint"] ?? ""),
    temperature: String(config["temperature"] ?? ""),
    top_p: String(config["top_p"] ?? ""),
    max_tokens: String(config["max_tokens"] ?? ""),
    response_format: String(config["response_format"] ?? ""),
    timeout_ms: String(config["timeout_ms"] ?? ""),
    metadata: String(config["metadata"] ?? ""),
  };
};

const parseNumberField = (value: string) => {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) return undefined;
  return parsed;
};

const COST_HINT_ROWS = [
  { model: "gpt-4o-mini", input: "$0.15 / 1M", output: "$0.60 / 1M" },
  { model: "gpt-4o", input: "$5.00 / 1M", output: "$15.00 / 1M" },
  { model: "gemini-1.5-flash", input: "$0.35 / 1M", output: "$1.05 / 1M" },
  { model: "gemini-1.5-pro", input: "$3.50 / 1M", output: "$10.50 / 1M" },
];

export function ProviderManagementPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [selectedProviderId, setSelectedProviderId] = useState<number | null>(null);
  const [drawerMode, setDrawerMode] = useState<"create" | "edit" | null>(null);
  const [editingProviderId, setEditingProviderId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Provider | null>(null);
  const [statusMessage, setStatusMessage] = useState<{ id: number; text: string; kind: "success" | "failed" } | null>(null);
  const [testingProviderId, setTestingProviderId] = useState<number | null>(null);

  const providersQuery = useQuery({
    queryKey: ["providers"],
    queryFn: listProviders,
  });

  const providers = providersQuery.data ?? [];

  const filteredProviders = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return providers;
    return providers.filter((provider) => {
      const parts = [provider.name, provider.provider, provider.model, provider.base_url ?? ""];
      return parts.some((part) => String(part).toLowerCase().includes(keyword));
    });
  }, [providers, search]);

  useEffect(() => {
    if (selectedProviderId && filteredProviders.some((provider) => provider.id === selectedProviderId)) return;
    if (!filteredProviders.length) {
      setSelectedProviderId(null);
      return;
    }
    setSelectedProviderId(filteredProviders[0].id);
  }, [filteredProviders, selectedProviderId]);

  const editingProvider = useMemo(
    () => providers.find((provider) => provider.id === editingProviderId) ?? null,
    [providers, editingProviderId],
  );

  const drawerInitialValues = useMemo(
    () => formatDrawerValues(drawerMode === "edit" ? editingProvider : null),
    [drawerMode, editingProvider],
  );

  const openCreateDrawer = () => {
    setEditingProviderId(null);
    setDrawerMode("create");
  };

  const openEditDrawer = (providerId: number) => {
    setSelectedProviderId(providerId);
    setEditingProviderId(providerId);
    setDrawerMode("edit");
  };

  const closeDrawer = () => {
    setDrawerMode(null);
    setEditingProviderId(null);
  };

  const saveProviderMutation = useMutation({
    mutationFn: async (payload: ProviderFormValues) => {
      const config = {
        provider_type: payload.provider,
        compatible_provider: payload.compatible_provider || undefined,
        custom_endpoint: payload.custom_endpoint.trim() || undefined,
        temperature: parseNumberField(payload.temperature),
        top_p: parseNumberField(payload.top_p),
        max_tokens: parseNumberField(payload.max_tokens),
        response_format: payload.response_format.trim() || undefined,
        timeout_ms: parseNumberField(payload.timeout_ms),
        metadata: payload.metadata.trim() || undefined,
      };
      const request = {
        name: payload.name.trim(),
        provider: "openai-compatible",
        model: payload.model.trim(),
        base_url: payload.base_url.trim(),
        api_key: payload.api_key.trim() || undefined,
        config,
      };

      if (drawerMode === "edit" && editingProvider) {
        return updateProvider(editingProvider.id, request);
      }
      return createProvider(request);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["providers"] });
      closeDrawer();
    },
  });

  const testProviderMutation = useMutation({
    mutationFn: testProvider,
    onMutate: (providerId: number) => {
      setTestingProviderId(providerId);
      setStatusMessage(null);
    },
    onSuccess: async (_data, providerId) => {
      setStatusMessage({
        id: providerId,
        text: t("settings.providers.management.testStatus.success"),
        kind: "success",
      });
      await queryClient.invalidateQueries({ queryKey: ["providers"] });
    },
    onError: async (_error, providerId) => {
      setStatusMessage({
        id: providerId,
        text: t("settings.providers.management.testStatus.failed"),
        kind: "failed",
      });
      await queryClient.invalidateQueries({ queryKey: ["providers"] });
    },
    onSettled: () => {
      setTestingProviderId(null);
    },
  });

  const deleteProviderMutation = useMutation({
    mutationFn: deleteProvider,
    onSuccess: async (_data, providerId) => {
      await queryClient.invalidateQueries({ queryKey: ["providers"] });
      setDeleteTarget(null);
      if (selectedProviderId === providerId) {
        setSelectedProviderId(null);
      }
    },
  });

  const defaultProviderMutation = useMutation({
    mutationFn: activateProvider,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["providers"] });
    },
  });

  const handleSubmit = (values: ProviderFormValues) => {
    saveProviderMutation.mutate(values);
  };

  const handleDeleteConfirm = () => {
    if (!deleteTarget) return;
    deleteProviderMutation.mutate(deleteTarget.id);
  };

  return (
    <div className="provider-management-page">
      <ProviderPageHeader
        title={t("settings.providers.management.pageTitle")}
        subtitle={t("settings.providers.management.pageSubtitle")}
        onAdd={openCreateDrawer}
      />

      <div className="provider-management-page__body">
        <ProviderCardList
          providers={filteredProviders}
          hasProviders={providers.length > 0}
          selectedProviderId={selectedProviderId}
          search={search}
          onSearchChange={setSearch}
          onSelectProvider={setSelectedProviderId}
          onEditProvider={openEditDrawer}
          onDeleteProvider={setDeleteTarget}
          onTestProvider={(providerId) => testProviderMutation.mutate(providerId)}
          onSetDefault={(providerId) => defaultProviderMutation.mutate(providerId)}
          testingProviderId={testingProviderId}
          statusMessage={statusMessage}
        />

        {!providersQuery.isLoading && providers.length === 0 ? (
          <ProviderEmptyState onAddProvider={openCreateDrawer} />
        ) : null}

        <section className="provider-cost-note" aria-label={t("settings.providers.costHintAriaLabel")}>
          <div className="provider-cost-note__header">
            <h2 className="provider-cost-note__title">{t("settings.providers.management.costNote.title")}</h2>
            <p className="provider-cost-note__subtitle">{t("settings.providers.management.costNote.subtitle")}</p>
          </div>
          <div className="provider-cost-note__table-wrap">
            <table className="provider-cost-note__table">
              <thead>
                <tr>
                  <th>{t("settings.providers.management.costNote.model")}</th>
                  <th>{t("settings.providers.management.costNote.inputPrice")}</th>
                  <th>{t("settings.providers.management.costNote.outputPrice")}</th>
                </tr>
              </thead>
              <tbody>
                {COST_HINT_ROWS.map((row) => (
                  <tr key={row.model}>
                    <td>{row.model}</td>
                    <td>{row.input}</td>
                    <td>{row.output}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <ProviderDrawerForm
        isOpen={drawerMode !== null}
        mode={drawerMode ?? "create"}
        provider={drawerMode === "edit" ? editingProvider : null}
        initialValues={drawerInitialValues}
        onClose={closeDrawer}
        onSubmit={handleSubmit}
        isSaving={saveProviderMutation.isPending}
      />

      <DeleteProviderDialog
        provider={deleteTarget}
        isOpen={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDeleteConfirm}
        isDeleting={deleteProviderMutation.isPending}
      />
    </div>
  );
}
