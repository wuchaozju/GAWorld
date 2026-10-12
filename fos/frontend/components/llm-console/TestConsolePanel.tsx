// frontend/components/llm-console/TestConsolePanel.tsx
import { useState } from "react";
import { Play, Copy, Trash2, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Provider } from "../../services/providers";
import type { ModelRecord } from "../../services/models";

type TestConsolePanelProps = {
  providers: Provider[];
  models: ModelRecord[];
  activeModelId: string | null;
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
  onSetActiveModel: (id: string) => void;
  onUpdateTestInput: (partial: any) => void;
  onSendTest: () => void;
  onClear: () => void;
  onTestConnection: () => void;
  isTestConnecting?: boolean;
  isTestSending?: boolean;
};

export function TestConsolePanel({
  providers,
  models,
  activeModelId,
  testInput,
  testResult,
  onSetActiveModel,
  onUpdateTestInput,
  onSendTest,
  onClear,
  onTestConnection,
  isTestConnecting = false,
  isTestSending = false,
}: TestConsolePanelProps) {
  const { t } = useTranslation();
  const [expandSystemPrompt, setExpandSystemPrompt] = useState(false);
  const [expandErrorLog, setExpandErrorLog] = useState(false);

  const activeModel = models.find((m) => m.id === activeModelId);
  const activeProvider = activeModel
    ? providers.find((p) => p.id === activeModel.providerId)
    : null;

  const handleCopyResult = () => {
    if (testResult.content) {
      navigator.clipboard.writeText(testResult.content);
    }
  };

  return (
    <div className="llm-test-console">
      <div className="llm-console-header">
        <h3 className="llm-console-title">
          {t("components.llmConsole.testConsole.title")}
        </h3>
        <div className="llm-console-model-badge">
          {activeModel ? (
            <>
              <span className="llm-badge-text">{activeModel.displayName}</span>
            </>
          ) : (
            <span className="llm-badge-text llm-text-muted">
              {t("components.llmConsole.testConsole.noModelSelected")}
            </span>
          )}
        </div>
      </div>

      {/* 模型选择 */}
      <div className="llm-console-section">
        <label className="llm-console-label">
          {t("components.llmConsole.testConsole.selectModel")}
        </label>
        <select
          className="llm-console-select"
          value={activeModelId || ""}
          onChange={(e) => onSetActiveModel(e.target.value)}
        >
          <option value="">
            {t("components.llmConsole.testConsole.modelPlaceholder")}
          </option>
          {models.filter((m) => m.enabled).map((model) => (
            <option key={model.id} value={model.id || ""}>
              {model.displayName} ({model.modelId}) · {model.providerId}
            </option>
          ))}
        </select>
      </div>

      {/* System Prompt */}
      <div className="llm-console-section">
        <button
          className="llm-console-label llm-expandable-header"
          onClick={() => setExpandSystemPrompt(!expandSystemPrompt)}
        >
          <ChevronDown
            size={14}
            style={{
              transform: expandSystemPrompt ? "rotate(180deg)" : "none",
            }}
          />
          <span>{t("components.llmConsole.testConsole.systemPrompt")}</span>
        </button>
        {expandSystemPrompt && (
          <textarea
            className="llm-console-textarea"
            value={testInput.systemPrompt}
            onChange={(e) =>
              onUpdateTestInput({ systemPrompt: e.target.value })
            }
            rows={4}
            placeholder={t("components.llmConsole.testConsole.promptPlaceholder")}
          />
        )}
      </div>

      {/* User Prompt */}
      <div className="llm-console-section">
        <label className="llm-console-label">
          {t("components.llmConsole.testConsole.userPrompt")} *
        </label>
        <textarea
          className="llm-console-textarea"
          value={testInput.userPrompt}
          onChange={(e) =>
            onUpdateTestInput({ userPrompt: e.target.value })
          }
          rows={5}
          placeholder={t("components.llmConsole.testConsole.userPromptPlaceholder")}
        />
      </div>

      {/* 参数 */}
      <div className="llm-console-params">
        <div className="llm-param-group">
          <label className="llm-param-label">
            {t("components.llmConsole.testConsole.temperature")}
          </label>
          <input
            type="range"
            min="0"
            max="2"
            step="0.1"
            value={testInput.temperature}
            onChange={(e) =>
              onUpdateTestInput({ temperature: Number(e.target.value) })
            }
            className="llm-param-slider"
          />
          <span className="llm-param-value">{testInput.temperature.toFixed(1)}</span>
        </div>

        <div className="llm-param-group">
          <label className="llm-param-label">
            {t("components.llmConsole.testConsole.maxTokens")}
          </label>
          <input
            type="number"
            min="1"
            max="8000"
            value={testInput.maxTokens}
            onChange={(e) =>
              onUpdateTestInput({ maxTokens: Number(e.target.value) })
            }
            className="llm-param-number"
          />
        </div>

        <div className="llm-param-group">
          <label className="llm-param-label">
            {t("components.llmConsole.testConsole.responseFormat")}
          </label>
          <select
            value={testInput.responseFormat}
            onChange={(e) =>
              onUpdateTestInput({
                responseFormat: e.target.value as "text" | "json",
              })
            }
            className="llm-param-select"
          >
            <option value="text">Text</option>
            <option value="json">JSON</option>
          </select>
        </div>
      </div>

      {/* 操作按钮 */}
      <div className="llm-console-actions">
        <button
          className="llm-button llm-button--secondary llm-button--sm"
          onClick={onTestConnection}
          disabled={isTestConnecting || !activeProvider}
          title={t("components.llmConsole.testConsole.testConnectionTitle")}
        >
          {isTestConnecting ? (
            <>
              <span className="llm-spinner" />
              <span>{t("components.llmConsole.testConsole.testing")}</span>
            </>
          ) : (
            <>
              <Play size={12} />
              <span>{t("components.llmConsole.testConsole.testConnection")}</span>
            </>
          )}
        </button>

        <button
          className="llm-button llm-button--primary llm-button--sm"
          onClick={onSendTest}
          disabled={isTestSending || !activeModel || !testInput.userPrompt}
          title={t("components.llmConsole.testConsole.sendTestTitle")}
        >
          {isTestSending ? (
            <>
              <span className="llm-spinner" />
              <span>{t("components.llmConsole.testConsole.sending")}</span>
            </>
          ) : (
            <>
              <Play size={12} />
              <span>{t("components.llmConsole.testConsole.sendTest")}</span>
            </>
          )}
        </button>

        <button
          className="llm-button llm-button--secondary llm-button--sm"
          onClick={onClear}
          disabled={!testInput.userPrompt && testResult.status === "idle"}
          title={t("components.llmConsole.testConsole.clearTitle")}
        >
          <Trash2 size={12} />
          <span>{t("components.llmConsole.testConsole.clear")}</span>
        </button>
      </div>

      {/* 结果展示 */}
      {testResult.status !== "idle" && (
        <div className="llm-console-result">
          <div
            className={`llm-result-header llm-result-header--${testResult.status}`}
          >
            <span className="llm-result-status">
              {testResult.status === "loading"
                ? t("components.llmConsole.testConsole.processing")
                : testResult.status === "success"
                  ? t("components.llmConsole.testConsole.success")
                  : t("components.llmConsole.testConsole.failed")}
            </span>
            <span className="llm-result-time">
              {testResult.responseTime.toFixed(2)}ms
              {testResult.tokensUsed && (
                <>
                  {" "}
                  · {testResult.tokensUsed.prompt} +{" "}
                  {testResult.tokensUsed.completion}
                </>
              )}
            </span>
          </div>

          {testResult.content && (
            <div className="llm-result-content">
              <div className="llm-result-actions-bar">
                <button
                  className="llm-icon-button llm-icon-button--sm"
                  onClick={handleCopyResult}
                  title={t("components.llmConsole.testConsole.copyTitle")}
                >
                  <Copy size={12} />
                </button>
              </div>
              <pre className="llm-result-text">{testResult.content}</pre>
            </div>
          )}

          {testResult.errorMessage && (
            <div className="llm-console-section">
              <button
                className="llm-console-label llm-expandable-header"
                onClick={() => setExpandErrorLog(!expandErrorLog)}
              >
                <ChevronDown
                  size={14}
                  style={{
                    transform: expandErrorLog ? "rotate(180deg)" : "none",
                  }}
                />
                <span>{t("components.llmConsole.testConsole.errorLog")}</span>
              </button>
              {expandErrorLog && (
                <pre className="llm-error-log">{testResult.errorMessage}</pre>
              )}
            </div>
          )}
        </div>
      )}

      {/* 提示信息 */}
      {!activeModel && (
        <div className="llm-console-hint">
          <p>
            {t("components.llmConsole.testConsole.hint")}
          </p>
        </div>
      )}
    </div>
  );
}
