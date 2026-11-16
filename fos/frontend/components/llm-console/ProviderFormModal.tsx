// frontend/components/llm-console/ProviderFormModal.tsx
import { useState, useEffect } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Provider } from "../../services/providers";

type ProviderFormModalProps = {
  isOpen: boolean;
  editingProvider: Provider | null;
  onClose: () => void;
  onSubmit: (data: {
    name: string;
    provider: string;
    model: string;
    base_url?: string;
    api_key?: string;
  }) => void | PromiseLike<void>;
};

export function ProviderFormModal({
  isOpen,
  editingProvider,
  onClose,
  onSubmit,
}: ProviderFormModalProps) {
  const { t } = useTranslation();
  const [formData, setFormData] = useState({
    name: "",
    provider: "openai-compatible",
    model: "",
    base_url: "",
    api_key: "",
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);

  useEffect(() => {
    if (editingProvider) {
      setFormData({
        name: editingProvider.name,
        provider: editingProvider.provider,
        model: editingProvider.model,
        base_url: editingProvider.base_url || "",
        api_key: "",
      });
    } else {
      setFormData({
        name: "",
        provider: "openai-compatible",
        model: "",
        base_url: "",
        api_key: "",
      });
    }
  }, [editingProvider, isOpen]);

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

  if (!isOpen) return null;

  return (
    <div className="llm-modal-overlay">
      <div className="llm-modal">
        <div className="llm-modal-header">
          <h2 className="llm-modal-title">
            {editingProvider
              ? t("components.llmConsole.providerForm.editTitle")
              : t("components.llmConsole.providerForm.newTitle")}
          </h2>
          <button className="llm-modal-close" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="llm-modal-form">
          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.providerForm.name")} *
            </label>
            <input
              type="text"
              required
              className="llm-form-input"
              value={formData.name}
              onChange={(e) =>
                setFormData({ ...formData, name: e.target.value })
              }
              placeholder={t("components.llmConsole.providerForm.namePlaceholder")}
            />
          </div>

          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.providerForm.type")} *
            </label>
            <select
              className="llm-form-input"
              value={formData.provider}
              onChange={(e) =>
                setFormData({ ...formData, provider: e.target.value })
              }
            >
              <option value="openai-compatible">{t("components.llmConsole.providerForm.typeOpenaiCompatible")}</option>
              <option value="deepseek">{t("components.llmConsole.providerForm.typeDeepseek")}</option>
              <option value="openrouter">{t("components.llmConsole.providerForm.typeOpenrouter")}</option>
              <option value="azure-openai">{t("components.llmConsole.providerForm.typeAzureOpenai")}</option>
              <option value="gemini">{t("components.llmConsole.providerForm.typeGoogleGemini")}</option>
              <option value="custom">{t("components.llmConsole.providerForm.typeCustom")}</option>
            </select>
          </div>

          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.providerForm.defaultModel")} *
            </label>
            <input
              type="text"
              required
              className="llm-form-input"
              value={formData.model}
              onChange={(e) =>
                setFormData({ ...formData, model: e.target.value })
              }
              placeholder={t("components.llmConsole.providerForm.defaultModelPlaceholder")}
            />
          </div>

          {formData.provider !== "gemini" && (
            <div className="llm-form-group">
              <label className="llm-form-label">
                {t("components.llmConsole.providerForm.baseUrl")}
              </label>
              <input
                type="url"
                className="llm-form-input"
                value={formData.base_url}
                onChange={(e) =>
                  setFormData({ ...formData, base_url: e.target.value })
                }
                placeholder={t("components.llmConsole.providerForm.baseUrlPlaceholder")}
              />
            </div>
          )}

          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.providerForm.apiKey")} *
            </label>
            <div className="llm-form-input-group">
              <input
                type={showApiKey ? "text" : "password"}
                required
                className="llm-form-input"
                value={formData.api_key}
                onChange={(e) =>
                  setFormData({ ...formData, api_key: e.target.value })
                }
                placeholder={t("components.llmConsole.providerForm.apiKeyPlaceholder")}
              />
              <button
                type="button"
                className="llm-form-visibility"
                onClick={() => setShowApiKey(!showApiKey)}
              >
                {showApiKey ? t("common.hide") : t("common.show")}
              </button>
            </div>
          </div>

          <div className="llm-modal-actions">
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
                ? t("components.llmConsole.providerForm.saving")
                : t("components.llmConsole.providerForm.save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
