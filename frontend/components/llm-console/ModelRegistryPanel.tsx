// frontend/components/llm-console/ModelRegistryPanel.tsx
import { useMemo, useState } from "react";
import { Plus, Download, Upload, Edit2, Trash2, Copy, CheckCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ModelRecord } from "../../services/models";
import type { Provider } from "../../services/providers";

type ModelRegistryPanelProps = {
  models: ModelRecord[];
  providers: Provider[];
  selectedModelId: string | null;
  searchQuery: string;
  providerFilter: number | null;
  capabilityFilter: string[];
  onlyEnabled: boolean;
  onSelectModel: (id: string) => void;
  onAddModel: () => void;
  onEditModel: (id: string) => void;
  onDeleteModel: (id: string) => void;
  onDuplicateModel: (id: string) => void;
  onSetDefault: (id: string) => void;
  onToggleEnabled: (id: string, enabled: boolean) => void;
  onSearch: (query: string) => void;
  onFilterProvider: (id: number | null) => void;
  onFilterCapabilities: (caps: string[]) => void;
  onToggleOnlyEnabled: (enabled: boolean) => void;
  onBatchImport: () => void;
  onExport: () => void;
};

export function ModelRegistryPanel({
  models,
  providers,
  selectedModelId,
  searchQuery,
  providerFilter,
  capabilityFilter,
  onlyEnabled,
  onSelectModel,
  onAddModel,
  onEditModel,
  onDeleteModel,
  onDuplicateModel,
  onSetDefault,
  onToggleEnabled,
  onSearch,
  onFilterProvider,
  onFilterCapabilities,
  onToggleOnlyEnabled,
  onBatchImport,
  onExport,
}: ModelRegistryPanelProps) {
  const { t } = useTranslation();
  const [hoveredModelId, setHoveredModelId] = useState<string | null>(null);

  const allCapabilities = useMemo(() => {
    const set = new Set<string>();
    models.forEach((m) => m.capabilities.forEach((c) => set.add(c)));
    return Array.from(set);
  }, [models]);

  const filteredModels = useMemo(() => {
    return models.filter((model) => {
      if (onlyEnabled && !model.enabled) return false;
      if (providerFilter && model.providerId !== providerFilter) return false;
      if (
        capabilityFilter.length > 0 &&
        !capabilityFilter.some((cap) => model.capabilities.includes(cap as any))
      ) {
        return false;
      }
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        return (
          model.displayName.toLowerCase().includes(q) ||
          model.modelId.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [models, onlyEnabled, providerFilter, capabilityFilter, searchQuery]);

  const getProviderName = (id: number) =>
    providers.find((p) => p.id === id)?.name || "—";

  return (
    <div className="llm-model-registry">
      {/* 工具栏 */}
      <div className="llm-registry-toolbar">
        <div className="llm-registry-search">
          <input
            type="text"
            className="llm-search-input"
            placeholder={t("components.llmConsole.registry.searchPlaceholder")}
            value={searchQuery}
            onChange={(e) => onSearch(e.target.value)}
          />
        </div>

        <div className="llm-registry-filters">
          <select
            className="llm-filter-select"
            value={providerFilter || ""}
            onChange={(e) =>
              onFilterProvider(e.target.value ? Number(e.target.value) : null)
            }
          >
            <option value="">
              {t("components.llmConsole.registry.allProviders")}
            </option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>

          <div className="llm-capability-filter">
            {allCapabilities.map((cap) => (
              <label key={cap} className="llm-capability-checkbox">
                <input
                  type="checkbox"
                  checked={capabilityFilter.includes(cap)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      onFilterCapabilities([...capabilityFilter, cap]);
                    } else {
                      onFilterCapabilities(
                        capabilityFilter.filter((c) => c !== cap)
                      );
                    }
                  }}
                />
                <span>{cap}</span>
              </label>
            ))}
          </div>

          <label className="llm-enabled-toggle">
            <input
              type="checkbox"
              checked={onlyEnabled}
              onChange={(e) => onToggleOnlyEnabled(e.target.checked)}
            />
            <span>{t("components.llmConsole.registry.enabledOnly")}</span>
          </label>
        </div>

        <div className="llm-registry-actions">
          <button
            className="llm-button llm-button--secondary"
            onClick={onBatchImport}
            title={t("components.llmConsole.registry.batchImportTitle")}
          >
            <Upload size={14} />
            <span>{t("components.llmConsole.registry.batchImport")}</span>
          </button>
          <button
            className="llm-button llm-button--secondary"
            onClick={onExport}
            title={t("components.llmConsole.registry.exportTitle")}
          >
            <Download size={14} />
            <span>{t("components.llmConsole.registry.export")}</span>
          </button>
          <button
            className="llm-button llm-button--primary"
            onClick={onAddModel}
            title={t("components.llmConsole.registry.newModelTitle")}
          >
            <Plus size={14} />
            <span>{t("components.llmConsole.registry.newModel")}</span>
          </button>
        </div>
      </div>

      {/* 模型列表 */}
      <div className="llm-model-table-wrap">
        <table className="llm-model-table">
          <thead>
            <tr>
              <th style={{ width: "200px" }}>
                {t("components.llmConsole.registry.modelName")}
              </th>
              <th style={{ width: "150px" }}>{t("components.llmConsole.registry.modelId")}</th>
              <th style={{ width: "120px" }}>{t("components.llmConsole.registry.provider")}</th>
              <th style={{ width: "100px" }}>
                {t("components.llmConsole.registry.protocol")}
              </th>
              <th style={{ width: "150px" }}>
                {t("components.llmConsole.registry.capabilities")}
              </th>
              <th style={{ width: "100px" }}>
                {t("components.llmConsole.registry.context")}
              </th>
              <th style={{ width: "100px" }}>
                {t("components.llmConsole.registry.price")}
              </th>
              <th style={{ width: "60px" }}>
                {t("components.llmConsole.registry.status")}
              </th>
              <th style={{ width: "120px" }}>
                {t("components.llmConsole.registry.lastTest")}
              </th>
              <th style={{ width: "180px" }}>
                {t("components.llmConsole.registry.actions")}
              </th>
            </tr>
          </thead>
          <tbody>
            {filteredModels.length === 0 ? (
              <tr>
                <td colSpan={10} className="llm-table-empty">
                  {t("components.llmConsole.registry.noMatching")}
                </td>
              </tr>
            ) : (
              filteredModels.map((model) => (
                <tr
                  key={model.id}
                  className={`llm-model-row ${
                    selectedModelId === model.id ? "is-selected" : ""
                  }`}
                  onMouseEnter={() => setHoveredModelId(model.id || null)}
                  onMouseLeave={() => setHoveredModelId(null)}
                  onClick={() => onSelectModel(model.id || "")}
                >
                  <td className="llm-cell-name">
                    <div className="llm-cell-content">
                      <strong>{model.displayName}</strong>
                      {model.isDefault && (
                        <span className="llm-badge llm-badge--small">
                          {t("components.llmConsole.registry.default")}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="llm-cell-mono">{model.modelId}</td>
                  <td className="llm-cell-provider">
                    {getProviderName(model.providerId)}
                  </td>
                  <td className="llm-cell-protocol">
                    <span className="llm-badge llm-badge--light">
                      {model.protocolType}
                    </span>
                  </td>
                  <td className="llm-cell-capabilities">
                    <div className="llm-caps-list">
                      {model.capabilities.slice(0, 2).map((cap) => (
                        <span key={cap} className="llm-cap-tag">
                          {cap}
                        </span>
                      ))}
                      {model.capabilities.length > 2 && (
                        <span className="llm-cap-more">
                          +{model.capabilities.length - 2}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="llm-cell-mono">
                    {(model.contextWindow / 1000).toFixed(0)}K
                  </td>
                  <td className="llm-cell-price">
                    {model.inputPrice ? (
                      <>
                        ${model.inputPrice.toFixed(2)} /
                        <br />
                        ${model.outputPrice?.toFixed(2) || "—"}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="llm-cell-status">
                    <input
                      type="checkbox"
                      checked={model.enabled}
                      onChange={(e) => {
                        e.stopPropagation();
                        onToggleEnabled(model.id || "", e.target.checked);
                      }}
                      title={t("components.llmConsole.registry.enableDisableTitle")}
                    />
                  </td>
                  <td className="llm-cell-test">
                    <span
                      className={`llm-test-status ${
                        model.lastTestStatus === "success"
                          ? "is-success"
                          : model.lastTestStatus === "failed"
                            ? "is-failed"
                            : ""
                      }`}
                    >
                      {model.lastTestStatus === "success"
                        ? "✓"
                        : model.lastTestStatus === "failed"
                          ? "✗"
                          : "—"}
                    </span>
                  </td>
                  <td className="llm-cell-actions">
                    {hoveredModelId === model.id && (
                      <div className="llm-action-buttons">
                        <button
                          className="llm-icon-button llm-icon-button--sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            onEditModel(model.id || "");
                          }}
                          title={t("components.llmConsole.registry.editTitle")}
                        >
                          <Edit2 size={12} />
                        </button>
                        <button
                          className="llm-icon-button llm-icon-button--sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDuplicateModel(model.id || "");
                          }}
                          title={t("components.llmConsole.registry.duplicateTitle")}
                        >
                          <Copy size={12} />
                        </button>
                        <button
                          className="llm-icon-button llm-icon-button--sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            onSetDefault(model.id || "");
                          }}
                          title={t("components.llmConsole.registry.setDefaultTitle")}
                        >
                          <CheckCircle size={12} />
                        </button>
                        <button
                          className="llm-icon-button llm-icon-button--sm llm-icon-button--danger"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (
                              window.confirm(
                                t("components.llmConsole.registry.confirmDelete")
                              )
                            ) {
                              onDeleteModel(model.id || "");
                            }
                          }}
                          title={t("components.llmConsole.registry.deleteTitle")}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="llm-table-footer">
        {t("components.llmConsole.registry.showingCount", { filtered: filteredModels.length, total: models.length })}
      </div>
    </div>
  );
}
