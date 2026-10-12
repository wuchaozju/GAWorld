// frontend/components/provider-management/DeleteProviderDialog.test.tsx
//
// Checks the "delete provider" confirm dialog close behaviour.
// The dialog must close only when the press starts and ends on the dark
// area around it, so picking text inside and dragging the mouse out never
// closes it by mistake.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DeleteProviderDialog } from "./DeleteProviderDialog";
import type { Provider } from "../../services/providers";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string): string =>
      (
        {
          "settings.providers.management.deleteDialog.title": "Delete provider",
          "settings.providers.management.deleteDialog.confirmMessage": "Delete {{name}}?",
          "settings.providers.management.deleteDialog.cancel": "Cancel",
          "settings.providers.management.deleteDialog.delete": "Delete",
          "settings.providers.management.deleteDialog.deleting": "Deleting…",
        } as Record<string, string>
      )[key] ?? key,
  }),
  Trans: ({ i18nKey, values }: { i18nKey: string; values?: Record<string, string> }) =>
    values?.name ?? i18nKey,
}));

const PROVIDER: Provider = {
  id: 1,
  name: "My Provider",
  provider: "openai-compatible",
  model: "gpt-4o",
  base_url: null,
  has_api_key: true,
};

function renderDialog(onClose: () => void = () => undefined): void {
  render(
    <DeleteProviderDialog
      provider={PROVIDER}
      isOpen
      onClose={onClose}
      onConfirm={() => undefined}
      isDeleting={false}
    />,
  );
}

describe("DeleteProviderDialog close behaviour", () => {
  it("test_pressing_and_releasing_on_the_outer_area_closes_the_dialog", () => {
    const onClose = vi.fn();
    renderDialog(onClose);

    const overlay = document.querySelector(".provider-dialog-overlay");
    expect(overlay).not.toBeNull();

    fireEvent.mouseDown(overlay as HTMLElement);
    fireEvent.mouseUp(overlay as HTMLElement);
    fireEvent.click(overlay as HTMLElement);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("test_dragging_the_mouse_out_of_the_dialog_while_picking_text_does_not_close_the_dialog", () => {
    const onClose = vi.fn();
    renderDialog(onClose);

    const dialog = screen.getByRole("dialog");
    const overlay = document.querySelector(".provider-dialog-overlay") as HTMLElement;

    fireEvent.mouseDown(dialog);
    fireEvent.mouseUp(overlay);
    fireEvent.click(overlay);

    expect(onClose).not.toHaveBeenCalled();
  });

  it("test_pressing_and_releasing_inside_the_dialog_does_not_close_it", () => {
    const onClose = vi.fn();
    renderDialog(onClose);

    const dialog = screen.getByRole("dialog");

    fireEvent.mouseDown(dialog);
    fireEvent.mouseUp(dialog);
    fireEvent.click(dialog);

    expect(onClose).not.toHaveBeenCalled();
  });
});
