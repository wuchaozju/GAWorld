/**
 * This file checks the provider data sent when the management page saves an LLM.
 * The test submits an Other provider and checks the request sent to the API.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createProvider, listProviders } from "../../services/providers";
import { ProviderManagementPage, type ProviderFormValues } from "./ProviderManagementPage";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string): string => key,
  }),
}));

vi.mock("../../services/providers", () => ({
  activateProvider: vi.fn(),
  createProvider: vi.fn(),
  deleteProvider: vi.fn(),
  listProviders: vi.fn(),
  testProvider: vi.fn(),
  updateProvider: vi.fn(),
}));

vi.mock("./ProviderPageHeader", () => ({
  ProviderPageHeader: ({ onAdd }: { onAdd: () => void }) => (
    <button type="button" onClick={onAdd}>
      Add LLM
    </button>
  ),
}));

vi.mock("./ProviderCardList", () => ({
  ProviderCardList: () => <div />,
}));

vi.mock("./ProviderEmptyState", () => ({
  ProviderEmptyState: () => <div />,
}));

vi.mock("./DeleteProviderDialog", () => ({
  DeleteProviderDialog: () => null,
}));

interface MockProviderDrawerFormProps {
  isOpen: boolean;
  onSubmit: (values: ProviderFormValues) => void;
}

vi.mock("./ProviderDrawerForm", () => ({
  ProviderDrawerForm: ({ isOpen, onSubmit }: MockProviderDrawerFormProps) => {
    if (!isOpen) return null;

    const submitOtherProvider = () => {
      onSubmit({
        name: "Other provider",
        provider: "custom",
        compatible_provider: "",
        base_url: "https://example.com/v1",
        api_key: "secret",
        model: "custom-model",
        custom_endpoint: "",
        temperature: "",
        top_p: "",
        max_tokens: "",
        response_format: "",
        timeout_ms: "",
        metadata: "",
      });
    };

    return (
      <button type="button" onClick={submitOtherProvider}>
        Submit other provider
      </button>
    );
  },
}));

function renderProviderManagementPage(): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <ProviderManagementPage />
    </QueryClientProvider>,
  );
}

describe("ProviderManagementPage", () => {
  beforeEach(() => {
    vi.mocked(listProviders).mockResolvedValue([]);
    vi.mocked(createProvider).mockResolvedValue({
      id: 1,
      name: "Other provider",
      provider: "openai-compatible",
      model: "custom-model",
      base_url: "https://example.com/v1",
      has_api_key: true,
    });
  });

  it("test_other_provider_uses_supported_runtime_provider", async () => {
    const user = userEvent.setup();
    renderProviderManagementPage();

    await user.click(screen.getByRole("button", { name: "Add LLM" }));
    await user.click(screen.getByRole("button", { name: "Submit other provider" }));

    await waitFor(() => expect(createProvider).toHaveBeenCalledTimes(1));
    expect(createProvider).toHaveBeenCalledWith(
      expect.objectContaining({
        provider: "openai-compatible",
        config: expect.objectContaining({
          provider_type: "custom",
          compatible_provider: undefined,
        }),
      }),
    );
  });
});
