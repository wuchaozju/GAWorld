// frontend/components/llm-console/StatusStrip.tsx
import { useMemo } from "react";
import { Plus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Provider } from "../../services/providers";
import type { ModelRecord } from "../../services/models";

type StatusStripProps = {
  providers: Provider[];
  models: ModelRecord[];
  activeProvider: Provider | undefined;
  defaultModel: ModelRecord | undefined;
  lastTestStatus?: "success" | "failed" | null;
  onAddProvider: () => void;
};

export function StatusStrip({
  providers,
  models,
  activeProvider,
  defaultModel,
  lastTestStatus,
  onAddProvider,
}: StatusStripProps) {
  const { t } = useTranslation();

  const enabledModels = useMemo(() => models.filter((m) => m.enabled), [models]);

  const statusColor =
    lastTestStatus === "success"
      ? "text-green-600"
      : lastTestStatus === "failed"
        ? "text-red-600"
        : "text-gray-500";

  return (
    <div className="llm-status-strip">
      <div className="llm-status-strip__inner">
        <div className="llm-status-strip__metrics">
          <div className="llm-status-item">
            <span className="llm-status-label">
              {t("components.llmConsole.status.providers")}
            </span>
            <strong className="llm-status-value">{providers.length}</strong>
          </div>

          <div className="llm-status-item">
            <span className="llm-status-label">
              {t("components.llmConsole.status.activeModels")}
            </span>
            <strong className="llm-status-value">{enabledModels.length}</strong>
          </div>

          <div className="llm-status-item">
            <span className="llm-status-label">
              {t("components.llmConsole.status.defaultModel")}
            </span>
            <strong className="llm-status-value">
              {defaultModel?.displayName || "—"}
            </strong>
          </div>

          <div className="llm-status-item">
            <span className="llm-status-label">
              {t("components.llmConsole.status.active")}
            </span>
            <strong className="llm-status-value">
              {activeProvider?.name || "—"}
            </strong>
          </div>

          <div className="llm-status-item">
            <span className="llm-status-label">
              {t("components.llmConsole.status.lastTest")}
            </span>
            <strong className={`llm-status-value ${statusColor}`}>
              {lastTestStatus === "success"
                ? t("components.llmConsole.status.testPass")
                : lastTestStatus === "failed"
                  ? t("components.llmConsole.status.testFailed")
                  : "—"}
            </strong>
          </div>
        </div>

        <div className="llm-status-strip__actions">
          <button
            className="llm-button llm-button--primary"
            onClick={onAddProvider}
            title={t("components.llmConsole.status.addProviderTitle")}
          >
            <Plus size={16} />
            <span>{t("components.llmConsole.status.newProvider")}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
