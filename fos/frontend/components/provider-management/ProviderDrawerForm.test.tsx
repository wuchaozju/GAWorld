/**
 * This file checks the provider choices in the LLM drawer.
 * Each test checks one small action a person can take in the provider menu.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProviderDrawerForm } from "./ProviderDrawerForm";
import type { ProviderFormValues } from "./ProviderManagementPage";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string): string =>
      (
        {
          "common.cancel": "Cancel",
          "settings.providers.type.openai": "OpenAI-compatible",
          "settings.providers.type.other": "Other",
          "settings.providers.compatibleProvider.chatgpt": "ChatGPT",
          "settings.providers.compatibleProvider.deepseek": "DeepSeek",
          "settings.providers.compatibleProvider.minimax": "MiniMax",
          "settings.providers.compatibleProvider.kimi": "Kimi",
          "settings.providers.providerForm.newLlmTitle": "New LLM",
          "settings.providers.providerForm.openaiCompatibleAccessConfig": "OpenAI-compatible access",
          "settings.providers.providerForm.openaiCompatibleProviders": "OpenAI-compatible providers",
          "settings.providers.providerForm.llmNameRequired": "LLM name",
          "settings.providers.providerForm.llmNamePlaceholder": "My LLM",
          "settings.providers.providerForm.providerTypeRequired": "Provider type",
          "settings.providers.providerForm.baseUrlRequired": "Base URL",
          "settings.providers.providerForm.baseUrlPlaceholder": "https://example.com/v1",
          "settings.providers.providerForm.apiKeyRequired": "API key",
          "settings.providers.providerForm.apiKeyPlaceholder": "API key",
          "settings.providers.providerForm.showApiKey": "Show API key",
          "settings.providers.providerForm.hideApiKey": "Hide API key",
          "settings.providers.providerForm.defaultModel": "Model",
          "settings.providers.providerForm.defaultModelPlaceholderOpenai": "gpt-4o-mini",
          "settings.providers.providerForm.advancedSettings": "Advanced settings",
          "settings.providers.providerForm.temperature": "Temperature",
          "settings.providers.providerForm.topP": "Top P",
          "settings.providers.providerForm.maxTokens": "Max tokens",
          "settings.providers.providerForm.responseFormat": "Response format",
          "settings.providers.providerForm.timeoutMs": "Timeout",
          "settings.providers.providerForm.customEndpoint": "Custom endpoint",
          "settings.providers.providerForm.headersMetadata": "Headers",
          "settings.providers.providerForm.optional": "Optional",
          "settings.providers.providerForm.advancedHint": "Optional settings",
          "settings.providers.providerForm.exampleDecimal07": "0.7",
          "settings.providers.providerForm.exampleDecimal10": "1.0",
          "settings.providers.providerForm.exampleMaxTokens": "4096",
          "settings.providers.providerForm.exampleJsonObject": "json_object",
          "settings.providers.providerForm.exampleTimeoutMs": "30000",
          "settings.providers.providerForm.save": "Save",
          "settings.providers.providerForm.saving": "Saving",
        } as Record<string, string>
      )[key] ?? key,
  }),
}));

const INITIAL_VALUES: ProviderFormValues = {
  name: "",
  provider: "openai-compatible",
  compatible_provider: "",
  base_url: "",
  api_key: "",
  model: "",
  custom_endpoint: "",
  temperature: "",
  top_p: "",
  max_tokens: "",
  response_format: "",
  timeout_ms: "",
  metadata: "",
};

// This helper opens the drawer with the same empty values each time.
// It lets each test pass its own close handler so close behaviour can be checked.
function renderProviderDrawer(onClose: () => void = () => undefined): void {
  render(
    <ProviderDrawerForm
      isOpen
      mode="create"
      provider={null}
      initialValues={INITIAL_VALUES}
      onClose={onClose}
      onSubmit={() => undefined}
      isSaving={false}
    />,
  );
}

describe("ProviderDrawerForm", () => {
  // This test checks that the first menu has only the two main choices.
  it("test_provider_type_menu_has_two_choices", async () => {
    const user = userEvent.setup();
    renderProviderDrawer();

    await user.click(screen.getByRole("button", { name: "Provider type" }));

    const menu = screen.getByRole("listbox", { name: "Provider type" });
    expect(within(menu).getAllByRole("option")).toHaveLength(2);
    expect(within(menu).getByRole("option", { name: "OpenAI-compatible" })).toBeInTheDocument();
    expect(within(menu).getByRole("option", { name: "Other" })).toBeInTheDocument();
  });

  // This test checks that picking OpenAI-compatible opens the provider menu.
  it("test_openai_compatible_choice_opens_provider_menu", async () => {
    const user = userEvent.setup();
    renderProviderDrawer();

    await user.click(screen.getByRole("button", { name: "Provider type" }));
    await user.click(screen.getByRole("option", { name: "OpenAI-compatible" }));

    expect(screen.getByRole("listbox", { name: "OpenAI-compatible providers" })).toBeInTheDocument();
  });

  // This test checks that the provider menu has only the requested providers.
  it("test_openai_compatible_provider_menu_has_requested_choices", async () => {
    const user = userEvent.setup();
    renderProviderDrawer();

    await user.click(screen.getByRole("button", { name: "Provider type" }));
    await user.click(screen.getByRole("option", { name: "OpenAI-compatible" }));

    const menu = screen.getByRole("listbox", { name: "OpenAI-compatible providers" });
    expect(within(menu).getAllByRole("option")).toHaveLength(4);
    expect(within(menu).getByRole("option", { name: "ChatGPT" })).toBeInTheDocument();
    expect(within(menu).getByRole("option", { name: "DeepSeek" })).toBeInTheDocument();
    expect(within(menu).getByRole("option", { name: "MiniMax" })).toBeInTheDocument();
    expect(within(menu).getByRole("option", { name: "Kimi" })).toBeInTheDocument();
  });

  // This test checks that Other can be picked without opening the provider menu.
  it("test_other_choice_can_be_picked_directly", async () => {
    const user = userEvent.setup();
    renderProviderDrawer();

    await user.click(screen.getByRole("button", { name: "Provider type" }));
    await user.click(screen.getByRole("option", { name: "Other" }));

    expect(screen.getByRole("button", { name: "Provider type" })).toHaveTextContent("Other");
    expect(screen.queryByRole("listbox", { name: "OpenAI-compatible providers" })).not.toBeInTheDocument();
  });
});

describe("ProviderDrawerForm close behaviour", () => {
  // This test checks that a normal click on the dark area around the drawer still closes it.
  it("test_pressing_and_releasing_on_the_outer_area_closes_the_drawer", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderProviderDrawer(onClose);

    const shell = document.querySelector(".provider-drawer-shell");
    expect(shell).not.toBeNull();

    await user.click(shell as HTMLElement);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // This test checks the bug: picking text inside the drawer and dragging the mouse
  // out of the drawer must not close it.
  it("test_dragging_the_mouse_out_of_the_drawer_while_picking_text_does_not_close_the_drawer", () => {
    const onClose = vi.fn();
    renderProviderDrawer(onClose);

    const drawer = screen.getByRole("dialog");
    const shell = document.querySelector(".provider-drawer-shell") as HTMLElement;

    // A browser starts the press on the text inside the drawer, releases the
    // button outside it, then fires the click on the outer area that wraps both.
    fireEvent.mouseDown(drawer);
    fireEvent.mouseUp(shell);
    fireEvent.click(shell);

    expect(onClose).not.toHaveBeenCalled();
  });

  // This test checks that pressing and releasing fully inside the drawer never closes it.
  it("test_pressing_and_releasing_inside_the_drawer_does_not_close_it", () => {
    const onClose = vi.fn();
    renderProviderDrawer(onClose);

    const drawer = screen.getByRole("dialog");

    fireEvent.mouseDown(drawer);
    fireEvent.mouseUp(drawer);
    fireEvent.click(drawer);

    expect(onClose).not.toHaveBeenCalled();
  });
});
