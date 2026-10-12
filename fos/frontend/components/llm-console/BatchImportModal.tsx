// frontend/components/llm-console/BatchImportModal.tsx
import { useState } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ModelRecord } from "../../services/models";
import type { Provider } from "../../services/providers";

type BatchImportModalProps = {
  isOpen: boolean;
  providers: Provider[];
  onClose: () => void;
  onImport: (models: Omit<ModelRecord, "id">[]) => void | PromiseLike<void>;
};

export function BatchImportModal({
  isOpen,
  providers,
  onClose,
  onImport,
}: BatchImportModalProps) {
  const { t } = useTranslation();
  const [importFormat, setImportFormat] = useState<"text" | "json">("text");
  const [importText, setImportText] = useState("");
  const [selectedProviderId, setSelectedProviderId] = useState<number | null>(
    providers.length > 0 ? providers[0].id : null
  );
  const [isImporting, setIsImporting] = useState(false);
  const [error, setError] = useState("");

  const handleImport = async () => {
    setError("");
    if (!selectedProviderId || !importText.trim()) {
      setError(t("components.llmConsole.batchImport.fillRequired"));
      return;
    }

    try {
      let models: Omit<ModelRecord, "id">[] = [];

      if (importFormat === "text") {
        // 按行解析
        const lines = importText
          .split("\n")
          .map((line) => line.trim())
          .filter((line) => line && !line.startsWith("#"));

        models = lines.map((line) => ({
          displayName: line,
          modelId: line,
          providerId: selectedProviderId,
          protocolType: "openai" as const,
          capabilities: ["text" as const],
          contextWindow: 4096,
          enabled: true,
          isDefault: false,
        }));
      } else {
        // JSON 解析
        try {
          const parsed = JSON.parse(importText);
          if (!Array.isArray(parsed)) {
            setError(t("components.llmConsole.batchImport.mustBeArray"));
            return;
          }
          models = parsed.map((item) => ({
            displayName: item.displayName || item.name || item.modelId,
            modelId: item.modelId || item.id,
            providerId: item.providerId || selectedProviderId,
            protocolType: item.protocolType || "openai",
            capabilities: item.capabilities || ["text"],
            contextWindow: item.contextWindow || 4096,
            inputPrice: item.inputPrice,
            outputPrice: item.outputPrice,
            tags: item.tags,
            enabled: item.enabled !== false,
            isDefault: item.isDefault || false,
          }));
        } catch (e) {
          setError(t("components.llmConsole.batchImport.jsonParseError"));
          return;
        }
      }

      if (models.length === 0) {
        setError(t("components.llmConsole.batchImport.noValidModels"));
        return;
      }

      setIsImporting(true);
      await onImport(models);
      setImportText("");
      onClose();
    } catch (e: any) {
      setError(e.message || t("components.llmConsole.batchImport.importFailed"));
    } finally {
      setIsImporting(false);
    }
  };

  if (!isOpen) return null;

  const exampleText = `gpt-4o-mini
gpt-4o
claude-3-opus
gemini-1.5-flash
gemini-1.5-pro`;

  const exampleJson = `[
  {
    "displayName": "GPT-4 Turbo",
    "modelId": "gpt-4-turbo",
    "capabilities": ["text", "vision"],
    "contextWindow": 128000,
    "inputPrice": 10,
    "outputPrice": 30
  },
  {
    "displayName": "Claude 3 Opus",
    "modelId": "claude-3-opus",
    "capabilities": ["text"],
    "contextWindow": 200000
  }
]`;

  return (
    <div className="llm-modal-overlay">
      <div className="llm-modal llm-modal--large">
        <div className="llm-modal-header">
          <h2 className="llm-modal-title">
            {t("components.llmConsole.batchImport.title")}
          </h2>
          <button className="llm-modal-close" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="llm-modal-form">
          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.batchImport.importFormat")}
            </label>
            <div className="llm-format-tabs">
              {["text", "json"].map((fmt) => (
                <button
                  key={fmt}
                  type="button"
                  className={`llm-format-tab ${
                    importFormat === fmt ? "is-active" : ""
                  }`}
                  onClick={() => setImportFormat(fmt as any)}
                >
                  {fmt.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <div className="llm-form-group">
            <label className="llm-form-label">
              {t("components.llmConsole.batchImport.selectProvider")} *
            </label>
            <select
              className="llm-form-input"
              value={selectedProviderId || ""}
              onChange={(e) => setSelectedProviderId(Number(e.target.value))}
            >
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div className="llm-form-group">
            <div className="llm-import-split">
              <div className="llm-import-input">
                <label className="llm-form-label">
                  {t("components.llmConsole.batchImport.inputData")} *
                </label>
                <textarea
                  className="llm-form-input llm-import-textarea"
                  value={importText}
                  onChange={(e) => setImportText(e.target.value)}
                  placeholder={
                    importFormat === "text"
                      ? t("components.llmConsole.batchImport.textPlaceholder")
                      : t("components.llmConsole.batchImport.jsonPlaceholder")
                  }
                />
              </div>

              <div className="llm-import-example">
                <label className="llm-form-label">
                  {t("components.llmConsole.batchImport.example")}
                </label>
                <pre className="llm-example-code">
                  {importFormat === "text" ? exampleText : exampleJson}
                </pre>
              </div>
            </div>
          </div>

          {error && (
            <div className="llm-form-error">
              <strong>{t("components.llmConsole.batchImport.errorLabel")}</strong> {error}
            </div>
          )}

          <div className="llm-modal-actions">
            <button
              type="button"
              className="llm-button llm-button--secondary"
              onClick={onClose}
              disabled={isImporting}
            >
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="llm-button llm-button--primary"
              onClick={handleImport}
              disabled={isImporting || !importText.trim()}
            >
              {isImporting
                ? t("components.llmConsole.batchImport.importing")
                : t("components.llmConsole.batchImport.importButton")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
