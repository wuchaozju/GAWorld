// frontend/components/provider-management/DeleteProviderDialog.tsx
//
// Shows the confirm dialog that appears before removing an LLM provider.
// The dialog closes only when a person presses and releases on the dark
// area around it. Picking text inside and dragging the mouse out no longer
// closes it by mistake.
import { useRef, type MouseEvent } from "react";
import type { Provider } from "../../services/providers";
import { Trans, useTranslation } from "react-i18next";

type DeleteProviderDialogProps = {
  provider: Provider | null;
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  isDeleting: boolean;
};

export function DeleteProviderDialog({
  provider,
  isOpen,
  onClose,
  onConfirm,
  isDeleting,
}: DeleteProviderDialogProps) {
  const { t } = useTranslation();

  // Remembers whether the current press began on the dark area around the dialog.
  const pressStartedOnBackdrop = useRef(false);

  // Notes where a press started so a text selection begun inside the dialog is respected.
  const handleBackdropMouseDown = (event: MouseEvent<HTMLDivElement>): void => {
    pressStartedOnBackdrop.current = event.target === event.currentTarget;
  };

  // Closes the dialog only when the press starts and ends on the dark area around it.
  const handleBackdropMouseUp = (event: MouseEvent<HTMLDivElement>): void => {
    const releasedOnBackdrop = event.target === event.currentTarget;
    if (pressStartedOnBackdrop.current && releasedOnBackdrop) {
      onClose();
    }
    pressStartedOnBackdrop.current = false;
  };

  if (!isOpen || !provider) return null;

  return (
    <div
      className="provider-dialog-overlay"
      role="presentation"
      onMouseDown={handleBackdropMouseDown}
      onMouseUp={handleBackdropMouseUp}
    >
      <div className="provider-dialog" role="dialog" aria-modal="true">
        <h3 className="provider-dialog__title">{t("settings.providers.management.deleteDialog.title")}</h3>
        <p className="provider-dialog__description">
          <Trans
            i18nKey="settings.providers.management.deleteDialog.confirmMessage"
            values={{ name: provider.name }}
            components={{ strong: <strong /> }}
          />
        </p>
        <div className="provider-dialog__actions">
          <button type="button" className="provider-button provider-button--ghost" onClick={onClose}>
            {t("settings.providers.management.deleteDialog.cancel")}
          </button>
          <button type="button" className="provider-button provider-button--danger" onClick={onConfirm} disabled={isDeleting}>
            {isDeleting ? t("settings.providers.management.deleteDialog.deleting") : t("settings.providers.management.deleteDialog.delete")}
          </button>
        </div>
      </div>
    </div>
  );
}
