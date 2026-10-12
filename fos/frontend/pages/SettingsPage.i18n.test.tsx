/**
 * This file tests SettingsPage language behavior in runtime rendering.
 * test_settings_page_shows_english_labels_by_default checks that stable labels show in English first.
 * test_settings_page_shows_chinese_labels_after_language_switch checks that the same labels show in Chinese.
 * test_settings_page_updates_labels_when_language_changes checks that labels change after switching language and rerendering.
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { SettingsPage } from "./SettingsPage";
import { useAuthStore } from "../store/auth";
import { resetLanguage, switchLanguage } from "../test-utils/i18n";

vi.mock("../components/provider-management/ProviderManagementPage", () => ({
  ProviderManagementPage: () => <div>Provider Management</div>,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const language = (globalThis as unknown as { i18n: { language: "en" | "zh" } }).i18n.language;
      const translations: Record<"en" | "zh", Record<string, string>> = {
        en: {
          "settings.title": "Settings",
          "settings.tabs.profile": "Profile",
          "settings.tabs.security": "Security",
          "settings.tabs.searchProviders": "Search Providers",
          "settings.tabs.files": "Files",
          "settings.tabHints.profile": "Identity and workspace ownership",
          "settings.workspaceStatus.authenticatedAccess": "Authenticated workspace access",
          "settings.subtitle": "Account and workspace settings",
          "settings.profile.email": "Email",
          "settings.profile.username": "Username",
          "settings.profile.fullName": "Full name",
          "settings.profile.organization": "Organization",
          "settings.workspaceTitle": "Workspace",
          "settings.workspaceHint": "Workspace controls and identity",
          brand: "Future of Society",
        },
        zh: {
          "settings.title": "设置",
          "settings.tabs.profile": "个人资料",
          "settings.tabs.security": "安全",
          "settings.tabs.searchProviders": "搜索提供商",
          "settings.tabs.files": "文件",
          "settings.tabHints.profile": "身份与工作空间归属",
          "settings.workspaceStatus.authenticatedAccess": "已验证的工作空间访问",
          "settings.subtitle": "账户和工作区设置",
          "settings.profile.email": "邮箱",
          "settings.profile.username": "用户名",
          "settings.profile.fullName": "姓名",
          "settings.profile.organization": "机构",
          "settings.workspaceTitle": "工作区",
          "settings.workspaceHint": "工作区控制和身份信息",
          brand: "社会未来",
        },
      };
      return translations[language][key] ?? key;
    },
    i18n: (globalThis as unknown as { i18n: { language: "en" | "zh" } }).i18n,
  }),
}));

function renderSettingsPage(): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/settings"]}>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("SettingsPage i18n", () => {
  beforeEach(async () => {
    await resetLanguage();
    useAuthStore.setState({
      user: {
        email: "researcher@example.com",
        username: "tester",
        full_name: "Test Researcher",
        organization: "FOS Lab",
      },
      clearSession: vi.fn(),
    } as never);
  });

  afterEach(async () => {
    await resetLanguage();
  });

  it("test_settings_page_shows_english_labels_by_default", () => {
    renderSettingsPage();
    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByText("Identity and workspace ownership")).toBeInTheDocument();
    expect(screen.getAllByText("Profile").length).toBeGreaterThan(0);
    expect(screen.getByText("Workspace")).toBeInTheDocument();
    expect(screen.getByText("Authenticated workspace access")).toBeInTheDocument();
  });

  it("test_settings_page_shows_chinese_labels_after_language_switch", async () => {
    await switchLanguage("zh");
    renderSettingsPage();
    expect(screen.getByRole("heading", { name: "设置" })).toBeInTheDocument();
    expect(screen.getByText("身份与工作空间归属")).toBeInTheDocument();
    expect(screen.getAllByText("个人资料").length).toBeGreaterThan(0);
    expect(screen.getByText("工作区")).toBeInTheDocument();
    expect(screen.getByText("已验证的工作空间访问")).toBeInTheDocument();
  });

  it("test_settings_page_updates_labels_when_language_changes", async () => {
    const { rerender } = renderSettingsPage();
    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByText("Identity and workspace ownership")).toBeInTheDocument();

    await switchLanguage("zh");
    rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={["/settings"]}>
          <SettingsPage />
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(screen.getByRole("heading", { name: "设置" })).toBeInTheDocument();
    expect(screen.getByText("身份与工作空间归属")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Settings" })).not.toBeInTheDocument();
    expect(screen.queryByText("Identity and workspace ownership")).not.toBeInTheDocument();
  });
});
