// frontend/components/provider-management/ProviderCard.tsx
import { Edit3, MoreHorizontal, Play, Trash2, Star } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Provider } from "../../services/providers";
import { ProviderStatusBadge } from "./ProviderStatusBadge";

type ProviderCardProps = {
  provider: Provider;
  isSelected: boolean;
  isTesting: boolean;
  onSelect: (providerId: number) => void;
  onEdit: (providerId: number) => void;
  onDelete: (provider: Provider) => void;
  onTest: (providerId: number) => void;
  onSetDefault: (providerId: number) => void;
  message?: { text: string; kind: "success" | "failed" } | null;
};

const getProviderLabel = (provider: string) => {
  if (provider.includes("gemini")) return "Google Gemini";
  return "OpenAI Compatible";
};

const formatBaseUrl = (baseUrl: string | null) => {
  if (!baseUrl) return "—";
  return baseUrl.length > 34 ? `${baseUrl.slice(0, 34)}…` : baseUrl;
};

export function ProviderCard({
  provider,
  isSelected,
  isTesting,
  onSelect,
  onEdit,
  onDelete,
  onTest,
  onSetDefault,
  message,
}: ProviderCardProps) {
  const { t } = useTranslation();
  const lastTestedAt = provider.last_tested_at
    ? new Date(provider.last_tested_at).toLocaleString()
    : "";

  return (
    <article
      className={`provider-card ${isSelected ? "is-selected" : ""}`}
      onClick={() => onSelect(provider.id)}
      role="button"
      tabIndex={0}
    >
      <div className="provider-card__top">
        <div className="provider-card__title-block">
          <div className="provider-card__title-row">
            <h3 className="provider-card__title">{provider.name}</h3>
            {provider.is_default ? <span className="provider-chip">{t("settings.providers.management.card.default")}</span> : null}
          </div>
          <div className="provider-card__meta-row">
            <span className="provider-card__type">{getProviderLabel(provider.provider)}</span>
            <span className="provider-card__dot-separator">·</span>
            <span className="provider-card__base-url" title={provider.base_url ?? ""}>
              {formatBaseUrl(provider.base_url)}
            </span>
          </div>
        </div>

        <ProviderStatusBadge status={provider.last_test_status} />
      </div>

      <div className="provider-card__body">
        <div className="provider-card__row">
          <span className="provider-card__label">{t("settings.providers.management.card.defaultModel")}</span>
          <strong className="provider-card__value">{provider.model || "—"}</strong>
        </div>
        <div className="provider-card__row">
          <span className="provider-card__label">{t("settings.providers.management.card.lastTest")}</span>
          <strong className="provider-card__value">{lastTestedAt || "—"}</strong>
        </div>
      </div>

      {message ? (
        <div className={`provider-card__message is-${message.kind}`}>
          {message.text}
        </div>
      ) : null}

      <div className="provider-card__actions">
        <button type="button" className="provider-icon-button" onClick={(event) => { event.stopPropagation(); onTest(provider.id); }} disabled={isTesting}>
          <Play size={14} />
          <span>{t("settings.providers.management.card.testConnection")}</span>
        </button>
        <button type="button" className="provider-icon-button" onClick={(event) => { event.stopPropagation(); onEdit(provider.id); }}>
          <Edit3 size={14} />
          <span>{t("settings.providers.management.card.edit")}</span>
        </button>
        <button type="button" className="provider-icon-button" onClick={(event) => { event.stopPropagation(); onSetDefault(provider.id); }}>
          <Star size={14} />
          <span>{t("settings.providers.management.card.setDefault")}</span>
        </button>
        <button type="button" className="provider-icon-button provider-icon-button--danger" onClick={(event) => { event.stopPropagation(); onDelete(provider); }}>
          <Trash2 size={14} />
          <span>{t("settings.providers.management.card.delete")}</span>
        </button>
      </div>
      <span className="provider-card__more-indicator" aria-hidden>
        <MoreHorizontal size={14} />
      </span>
    </article>
  );
}
