/**
 * This file shows a visible message while a page or part of a page is downloading.
 *
 * RouteLoading displays the shared loading text and can fill either a page or a smaller panel.
 */

import { useTranslation } from "react-i18next";

interface RouteLoadingProps {
  compact?: boolean;
}

export function RouteLoading({ compact = false }: RouteLoadingProps) {
  const { t } = useTranslation();

  return (
    <div
      className={compact ? "route-loading route-loading--compact" : "route-loading"}
      role="status"
      aria-live="polite"
    >
      <span className="spinner" aria-hidden />
      <span>{t("common.loading")}</span>
    </div>
  );
}
