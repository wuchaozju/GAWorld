// frontend/components/provider-management/ProviderStatusBadge.tsx
import { useTranslation } from "react-i18next";

type ProviderStatusBadgeProps = {
  status?: string | null;
};

export function ProviderStatusBadge({ status }: ProviderStatusBadgeProps) {
  const { t } = useTranslation();
  const STATUS_MAP: Record<string, { label: string; className: string }> = {
    success: { label: t("settings.providers.management.status.connected"), className: "is-success" },
    failed: { label: t("settings.providers.management.status.failed"), className: "is-error" },
    pending: { label: t("settings.providers.management.status.testing"), className: "is-pending" },
  };

  const entry = status ? STATUS_MAP[status] : null;
  const label = entry?.label ?? t("settings.providers.management.status.untested");
  const className = entry?.className ?? "is-muted";

  return (
    <span className={`provider-status-badge ${className}`}>
      <span className="provider-status-badge__dot" />
      <span>{label}</span>
    </span>
  );
}
