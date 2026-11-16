// frontend/components/llm-console/ModelEditorDrawer.tsx
import { useState, useEffect } from "react";
import { X, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ModelRecord } from "../../services/models";
import type { Provider } from "../../services/providers";

const CAPABILITY_OPTIONS = ["text", "vision", "audio", "json", "function_call", "reasoning"];

type ModelEditorDrawerProps = {
  isOpen: boolean;
  editingModel: ModelRecord | null;
  providers: Provider[];
  onClose: () => void;
  onSubmit: (data: Omit<ModelRecord, "id"> | Partial<ModelRecord>) => void | PromiseLike<void>;
};

export function ModelEditorDrawer({
  isOpen,
  editingModel,
  providers,
  onClose,
  onSubmit,
}: ModelEditorDrawerProps) {
  const { t } = useTranslation();
  const [formData, setFormData] = useState<Omit<ModelRecord, "id">>({
    displayName: "",
    modelId: "",
    providerId: 0,
    protocolType: "openai",
    capabilities: ["text"],
    contextWindow: 4096,
    inputPrice: undefined,
    outputPrice: undefined,
    tags: [],
    enabled: true,
    isDefault: false,
  });
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (editingModel) {
      setFormData(editingModel);
    } else {
      setFormData({
        displayName: "",
        modelId: "",
        providerId: providers.length > 0 ? providers[0].id : 0,
        protocolType: "openai",
        capabilities: ["text"],
        contextWindow: 4096,
        inputPrice: undefined,
        outputPrice: undefined,
        tags: [],
        enabled: true,
        isDefault: false,
      });
    }
  }, [editingModel, providers, isOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      await onSubmit(formData);
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  const toggleCapability = (cap: string) => {
    setFormData((prev) => ({
      ...prev,
      capabilities: prev.capabilities.includes(cap as any)
        ? prev.capabilities.filter((c) => c !== cap)
        : ([...prev.capabilities, cap] as any),
    }));
  };

  if (!isOpen) return null;

  return (
    <div className={`llm-drawer ${isOpen ? "is-open" : ""}`}>
      <div className="llm-drawer-overlay" onClick={onClose} />
      <div className="llm-drawer-content">
        <div className="llm-drawer-header">
          <h2 className="llm-drawer-title">
            {editingModel
              ? t("components.llmConsole.modelEditor.editTitle")
              : t("components.llmConsole.modelEditor.newTitle")}
          </h2>
          <button className="llm-drawer-close" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="llm-drawer-form">
          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.modelEditor.displayName")} *
            </label>
            <input
              type="text"
              required
              className="llm-form-input"
              value={formData.displayName}
              onChange={(e) =>
                setFormData({ ...formData, displayName: e.target.value })
              }
              placeholder={t("components.llmConsole.modelEditor.displayNamePlaceholder")}
            />
          </div>

          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.modelEditor.modelId")} *
            </label>
            <input
              type="text"
              required
              className="llm-form-input"
              value={formData.modelId}
              onChange={(e) =>
                setFormData({ ...formData, modelId: e.target.value })
              }
              placeholder={t("components.llmConsole.modelEditor.modelIdPlaceholder")}
            />
          </div>

          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.modelEditor.provider")} *
            </label>
            <select
              required
              className="llm-form-input"
              value={formData.providerId}
              onChange={(e) =>
                setFormData({ ...formData, providerId: Number(e.target.value) })
              }
            >
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.modelEditor.protocolType")} *
            </label>
            <select
              required
              className="llm-form-input"
              value={formData.protocolType}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  protocolType: e.target.value as any,
                })
              }
            >
              <option value="openai">{t("components.llmConsole.modelEditor.protocolOpenai")}</option>
              <option value="google">{t("components.llmConsole.modelEditor.protocolGoogle")}</option>
              <option value="custom">{t("components.llmConsole.modelEditor.protocolCustom")}</option>
            </select>
          </div>

          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.modelEditor.capabilities")}
            </label>
            <div className="llm-capability-checkboxes">
              {CAPABILITY_OPTIONS.map((cap) => (
                <label key={cap} className="llm-checkbox-item">
                  <input
                    type="checkbox"
                    checked={formData.capabilities.includes(cap as any)}
                    onChange={() => toggleCapability(cap)}
                  />
                  <span>{cap}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.modelEditor.contextWindow")} *
            </label>
            <input
              type="number"
              required
              className="llm-form-input"
              value={formData.contextWindow}
              onChange={(e) =>
                setFormData({ ...formData, contextWindow: Number(e.target.value) })
              }
              placeholder="4096"
            />
            <span className="llm-form-hint">
              {t("components.llmConsole.modelEditor.maxTokens")}
            </span>
          </div>

          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.modelEditor.inputPrice")} {t("components.llmConsole.modelEditor.perMillionTokens")}
            </label>
            <input
              type="number"
              step="0.001"
              className="llm-form-input"
              value={formData.inputPrice || ""}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  inputPrice: e.target.value ? Number(e.target.value) : undefined,
                })
              }
              placeholder="0.01"
            />
          </div>

          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.modelEditor.outputPrice")} {t("components.llmConsole.modelEditor.perMillionTokens")}
            </label>
            <input
              type="number"
              step="0.001"
              className="llm-form-input"
              value={formData.outputPrice || ""}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  outputPrice: e.target.value ? Number(e.target.value) : undefined,
                })
              }
              placeholder="0.03"
            />
          </div>

          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.modelEditor.tags")}
            </label>
            <div className="llm-tags-input">
              {formData.tags?.map((tag, idx) => (
                <span key={idx} className="llm-tag">
                  {tag}
                  <button
                    type="button"
                    onClick={() => {
                      setFormData({
                        ...formData,
                        tags: formData.tags?.filter((_, i) => i !== idx),
                      });
                    }}
                  >
                    <X size={10} />
                  </button>
                </span>
              ))}
              <input
                type="text"
                placeholder={t("components.llmConsole.modelEditor.tagsPlaceholder")}
                onKeyPress={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    const value = (e.target as HTMLInputElement).value.trim();
                    if (value) {
                      setFormData({
                        ...formData,
                        tags: [...(formData.tags || []), value],
                      });
                      (e.target as HTMLInputElement).value = "";
                    }
                  }
                }}
              />
            </div>
          </div>

          <div className="llm-form-group">
            <label className="llm-checkbox-label">
              <input
                type="checkbox"
                checked={formData.enabled}
                onChange={(e) =>
                  setFormData({ ...formData, enabled: e.target.checked })
                }
              />
              <span>{t("components.llmConsole.modelEditor.enableModel")}</span>
            </label>
          </div>

          <div className="llm-form-group">
            <label className="llm-checkbox-label">
              <input
                type="checkbox"
                checked={formData.isDefault}
                onChange={(e) =>
                  setFormData({ ...formData, isDefault: e.target.checked })
                }
              />
              <span>{t("components.llmConsole.modelEditor.setDefault")}</span>
            </label>
          </div>

          <div className="llm-drawer-actions">
            <button
              type="button"
              className="llm-button llm-button--secondary"
              onClick={onClose}
              disabled={isSubmitting}
            >
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              className="llm-button llm-button--primary"
              disabled={isSubmitting}
            >
              {isSubmitting
                ? t("components.llmConsole.modelEditor.saving")
                : t("components.llmConsole.modelEditor.save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
