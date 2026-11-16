/**
 * This file manages web-search provider settings when that tab is open.
 *
 * SearchProviderSettingsTab loads the saved provider, edits its fields, and saves the changes.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FilePlusIcon } from "@radix-ui/react-icons";
import { useTranslation } from "react-i18next";

import { AppSelect } from "../../components/AppSelect";
import {
  createSearchProvider,
  listSearchProviders,
  updateSearchProvider,
} from "../../services/searchProviders";

interface SearchDraft {
  provider: string;
  base_url: string;
  api_key: string;
  config: Record<string, unknown>;
}

function configText(config: Record<string, unknown>, key: string, fallback = ""): string {
  return String(config[key] ?? fallback);
}

export default function SearchProviderSettingsTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<SearchDraft>({
    provider: "ddg",
    base_url: "",
    api_key: "",
    config: { region: "", safesearch: "moderate" },
  });
  const query = useQuery({ queryKey: ["searchProviders"], queryFn: listSearchProviders });
  const provider = query.data?.[0] ?? null;

  useEffect(() => {
    if (!provider) return;
    setDraft({
      provider: provider.provider || "ddg",
      base_url: String(provider.base_url || ""),
      api_key: "",
      config: provider.config || {},
    });
  }, [provider]);

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        provider: draft.provider,
        base_url: draft.base_url || null,
        api_key: draft.api_key || null,
        config: draft.config,
      };
      return provider
        ? updateSearchProvider(provider.id, payload)
        : createSearchProvider({ ...payload, base_url: draft.base_url, api_key: draft.api_key });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["searchProviders"] }),
  });

  const updateConfig = (key: string, value: unknown): void => {
    setDraft((current) => ({ ...current, config: { ...current.config, [key]: value } }));
  };

  return (
    <div className="ss-settings-grid ss-settings-grid--split">
      <section className="card">
        <div className="panel-title">{t("settings.providers.searchTitle")}</div>
        <div className="panel-subtitle">{t("settings.providers.searchAlignmentHint")}</div>
        {query.isError ? <div className="ss-settings-error">{t("settings.providers.error")}</div> : null}
        <div className="ss-settings-info-grid">
          <div className="ss-settings-info-row"><span>{t("settings.providers.fields.provider")}</span><strong>{provider?.provider || "-"}</strong></div>
          <div className="ss-settings-info-row"><span>{t("settings.providers.fields.baseUrl")}</span><strong>{provider?.base_url || "-"}</strong></div>
        </div>
      </section>

      <section className="card">
        <div className="panel-title">{t("settings.providers.setSearchProvider")}</div>
        <div className="ss-settings-form-grid">
          <label>
            <span className="ss-form-label">{t("settings.providers.fields.provider")}</span>
            <AppSelect
              value={draft.provider}
              options={["ddg", "serpapi", "serper", "tavily", "mock"].map((value) => ({
                value,
                label: value === "mock" ? "Mock" : t(`settings.providers.searchEngine.${value}`),
              }))}
              onChange={(value) => setDraft((current) => ({ ...current, provider: value }))}
            />
          </label>

          {draft.provider !== "ddg" && draft.provider !== "mock" ? (
            <>
              <label>
                <span className="ss-form-label">{t("settings.providers.fields.baseUrl")}</span>
                <input value={draft.base_url} onChange={(event) => setDraft((current) => ({ ...current, base_url: event.target.value }))} />
              </label>
              <label>
                <span className="ss-form-label">{t("settings.providers.fields.apiKey")}</span>
                <input value={draft.api_key} onChange={(event) => setDraft((current) => ({ ...current, api_key: event.target.value }))} />
              </label>
            </>
          ) : null}

          {draft.provider === "ddg" ? (
            <>
              <label>
                <span className="ss-form-label">{t("settings.providers.search.region")}</span>
                <input value={configText(draft.config, "region")} onChange={(event) => updateConfig("region", event.target.value)} />
              </label>
              <label>
                <span className="ss-form-label">{t("settings.providers.search.safeSearch")}</span>
                <input value={configText(draft.config, "safesearch", "moderate")} onChange={(event) => updateConfig("safesearch", event.target.value)} />
              </label>
            </>
          ) : null}

          {draft.provider === "tavily" ? (
            <>
              <label>
                <span className="ss-form-label">{t("settings.providers.search.searchDepth")}</span>
                <AppSelect
                  value={configText(draft.config, "search_depth", "basic")}
                  options={[{ value: "basic", label: "basic" }, { value: "advanced", label: "advanced" }]}
                  onChange={(value) => updateConfig("search_depth", value)}
                />
              </label>
              <label>
                <span className="ss-form-label">{t("settings.providers.search.topic")}</span>
                <input value={configText(draft.config, "topic")} onChange={(event) => updateConfig("topic", event.target.value)} />
              </label>
              <label>
                <span className="ss-form-label">{t("settings.providers.search.days")}</span>
                <input type="number" min={1} value={Number(draft.config.days ?? 7)} onChange={(event) => updateConfig("days", Number(event.target.value || 0))} />
              </label>
              <label>
                <span className="ss-form-label">{t("settings.providers.search.includeDomains")}</span>
                <input value={configText(draft.config, "include_domains")} onChange={(event) => updateConfig("include_domains", event.target.value)} />
              </label>
            </>
          ) : null}
        </div>
        <button type="button" className="ss-button" onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? <span className="spinner" aria-hidden /> : <FilePlusIcon />}
          <span>{t("settings.providers.save")}</span>
        </button>
      </section>
    </div>
  );
}
