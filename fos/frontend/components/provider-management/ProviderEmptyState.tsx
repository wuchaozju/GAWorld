// frontend/components/provider-management/ProviderEmptyState.tsx
import { Server } from "lucide-react";
import { useTranslation } from "react-i18next";

type ProviderEmptyStateProps = {
  onAddProvider: () => void;
};

export function ProviderEmptyState({ onAddProvider }: ProviderEmptyStateProps) {
  const { t } = useTranslation();
  return (
    <section className="provider-empty-state">
      <div className="provider-empty-state__icon">
        <Server size={28} />
      </div>
      <h2>{t("settings.providers.management.noLlmYet")}</h2>
      <p>{t("settings.providers.management.supportsOpenaiAndGemini")}</p>
      <button type="button" className="provider-button provider-button--primary" onClick={onAddProvider}>
        {t("settings.providers.management.addLlm")}
      </button>
    </section>
  );
}
