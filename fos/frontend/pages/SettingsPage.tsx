/**
 * This file shows account and system settings without downloading every settings tool at once.
 *
 * SettingsPage reads the selected tab from the address and displays its panel.
 * ProfileTab shows saved account details.
 * SecurityTab provides sign-out controls.
 * InfoRow displays one account label and value.
 */

import { Suspense, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Bot, Database, FileStack, LogOut, Search, Shield, UserCircle2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { RouteLoading } from "../components/RouteLoading";
import { TitleCard } from "../components/TitleCard";
import { lazyWithRetry } from "../utils/lazyWithRetry";
import { useAuthStore } from "../store/auth";
import "../styles/routes/settings.css";

type Tab = "profile" | "security" | "providers_llm" | "providers_search" | "files" | "dataSources";

const ProviderSettingsTab = lazyWithRetry(
  () => import("./settings/ProviderSettingsTab"),
  "settings-providers",
);
const SearchProviderSettingsTab = lazyWithRetry(
  () => import("./settings/SearchProviderSettingsTab"),
  "settings-search-providers",
);
const FileSettingsTab = lazyWithRetry(
  () => import("./settings/FileSettingsTab"),
  "settings-files",
);
const DataSourcesSettingsTab = lazyWithRetry(
  () => import("./settings/DataSourcesSettingsTab"),
  "settings-data-sources",
);

function isTab(value: string | null): value is Tab {
  return (
    value === "profile" ||
    value === "security" ||
    value === "providers_llm" ||
    value === "providers_search" ||
    value === "files" ||
    value === "dataSources"
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="ss-settings-info-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ProfileTab() {
  const { t } = useTranslation();
  const user = useAuthStore((state) => state.user);
  const rows = [
    [t("settings.profile.email"), String(user?.email ?? "-")],
    [t("settings.profile.username"), String(user?.username ?? "-")],
    [t("settings.profile.fullName"), String(user?.full_name ?? "-")],
    [t("settings.profile.organization"), String(user?.organization ?? "-")],
  ];

  return (
    <div className="ss-settings-section">
      <section className="ss-settings-hero ss-surface-strong">
        <div>
          <div className="kicker">{t("settings.tabs.profile")}</div>
          <h2 className="section-title">{String(user?.full_name ?? user?.username ?? t("brand"))}</h2>
          <p className="panel-subtitle">{t("settings.subtitle")}</p>
        </div>
        <div className="ss-settings-info-grid">
          {rows.map(([label, value]) => <InfoRow key={label} label={label} value={value} />)}
        </div>
      </section>
      <div className="ss-settings-grid">
        <section className="card">
          <div className="panel-title">{t("settings.tabs.profile")}</div>
          <div className="panel-subtitle">{t("settings.profile.consistencyHint")}</div>
          <div className="ss-settings-info-grid">
            {rows.map(([label, value]) => <InfoRow key={label} label={label} value={value} />)}
          </div>
        </section>
        <section className="card">
          <div className="panel-title">{t("settings.workspaceTitle")}</div>
          <div className="panel-subtitle">{t("settings.workspaceHint")}</div>
          <div className="ss-settings-stack">
            <div className="ss-pill ss-pill--quiet"><Shield size={14} /><span>{t("settings.workspaceStatus.authenticatedAccess")}</span></div>
            <div className="ss-pill ss-pill--quiet"><Database size={14} /><span>{t("settings.workspaceStatus.profileReuse")}</span></div>
          </div>
        </section>
      </div>
    </div>
  );
}

function SecurityTab() {
  const { t } = useTranslation();
  const clearSession = useAuthStore((state) => state.clearSession);
  return (
    <div className="ss-settings-grid">
      <section className="card">
        <div className="panel-title">{t("settings.security.sessionsTitle")}</div>
        <div className="panel-subtitle">{t("settings.security.placeholder")}</div>
        <button type="button" className="ss-button-danger" onClick={clearSession}>
          <LogOut size={15} /><span>{t("settings.security.signoutAll")}</span>
        </button>
      </section>
      <section className="card">
        <div className="panel-title">{t("settings.security.controlTitle")}</div>
        <div className="panel-subtitle">{t("settings.security.controlHint")}</div>
        <div className="ss-settings-note">{t("settings.security.authFlowNote")}</div>
      </section>
    </div>
  );
}

export function SettingsPage() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<Tab>("profile");

  useEffect(() => {
    const nextTab = new URLSearchParams(location.search).get("tab");
    if (isTab(nextTab)) setActiveTab(nextTab);
  }, [location.search]);

  const selectTab = (tab: Tab): void => {
    setActiveTab(tab);
    const params = new URLSearchParams(location.search);
    params.set("tab", tab);
    navigate({ pathname: location.pathname, search: params.toString() }, { replace: true });
  };

  const tabs = [
    { id: "profile" as const, title: t("settings.tabs.profile"), hint: t("settings.tabHints.profile"), icon: <UserCircle2 size={15} /> },
    { id: "security" as const, title: t("settings.tabs.security"), hint: t("settings.tabHints.security"), icon: <Shield size={15} /> },
    { id: "providers_llm" as const, title: t("settings.tabs.llmProviders"), hint: t("settings.tabHints.providersLlm"), icon: <Bot size={15} /> },
    { id: "providers_search" as const, title: t("settings.tabs.searchProviders"), hint: t("settings.tabHints.providersSearch"), icon: <Search size={15} /> },
    { id: "files" as const, title: t("settings.tabs.files"), hint: t("settings.tabHints.files"), icon: <FileStack size={15} /> },
    { id: "dataSources" as const, title: t("settings.tabs.dataSources"), hint: t("settings.tabHints.dataSources"), icon: <Database size={15} /> },
  ];

  const activePanel = activeTab === "profile" ? <ProfileTab />
    : activeTab === "security" ? <SecurityTab />
      : activeTab === "providers_llm" ? <ProviderSettingsTab />
        : activeTab === "providers_search" ? <SearchProviderSettingsTab />
          : activeTab === "files" ? <FileSettingsTab />
            : <DataSourcesSettingsTab />;

  return (
    <div className="ss-product-page ss-product-page--settings scroll-panel">
      <TitleCard title={t("settings.title")} />
      <div className="tab-layout ss-settings-page__layout">
        <nav className="tab-nav ss-settings-page__nav">
          {tabs.map((item) => (
            <button key={item.id} type="button" className={`tab-button ss-settings-page__tab ${activeTab === item.id ? "active" : ""}`} onClick={() => selectTab(item.id)}>
              <span className="ss-settings-page__tab-icon">{item.icon}</span>
              <span className="ss-settings-page__tab-copy"><strong>{item.title}</strong><span>{item.hint}</span></span>
            </button>
          ))}
        </nav>
        <section className="ss-settings-page__content">
          <Suspense fallback={<RouteLoading compact />}>{activePanel}</Suspense>
        </section>
      </div>
    </div>
  );
}
