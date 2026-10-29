// frontend/components/provider-management/ProviderCardList.tsx
import { Search, Server } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Provider } from "../../services/providers";
import { ProviderCard } from "./ProviderCard";

type ProviderCardListProps = {
  providers: Provider[];
  hasProviders: boolean;
  selectedProviderId: number | null;
  search: string;
  onSearchChange: (value: string) => void;
  onSelectProvider: (providerId: number) => void;
  onEditProvider: (providerId: number) => void;
  onDeleteProvider: (provider: Provider) => void;
  onTestProvider: (providerId: number) => void;
  onSetDefault: (providerId: number) => void;
  testingProviderId: number | null;
  statusMessage: { id: number; text: string; kind: "success" | "failed" } | null;
};

export function ProviderCardList({
  providers,
  hasProviders,
  selectedProviderId,
  search,
  onSearchChange,
  onSelectProvider,
  onEditProvider,
  onDeleteProvider,
  onTestProvider,
  onSetDefault,
  testingProviderId,
  statusMessage,
}: ProviderCardListProps) {
  const { t } = useTranslation();
  return (
    <section className="provider-card-list-shell">
      <div className="provider-card-list-toolbar">
        <div className="provider-search-box">
          <Search size={16} />
          <input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={t("settings.providers.management.searchPlaceholder")}
            className="provider-search-input"
          />
        </div>
        <div className="provider-card-list-count">{t("settings.providers.management.llmCount", { count: providers.length })}</div>
      </div>

      <div className="provider-card-grid">
        {providers.map((provider) => (
          <ProviderCard
            key={provider.id}
            provider={provider}
            isSelected={selectedProviderId === provider.id}
            isTesting={testingProviderId === provider.id}
            onSelect={onSelectProvider}
            onEdit={onEditProvider}
            onDelete={onDeleteProvider}
            onTest={onTestProvider}
            onSetDefault={onSetDefault}
            message={statusMessage && statusMessage.id === provider.id ? { text: statusMessage.text, kind: statusMessage.kind } : null}
          />
        ))}
      </div>

      {providers.length === 0 && hasProviders ? (
        <div className="provider-card-list-empty">
          <Server size={28} />
          <p>{search ? t("settings.providers.management.noMatchingLlm") : t("settings.providers.management.noLlmYet")}</p>
        </div>
      ) : null}
    </section>
  );
}
