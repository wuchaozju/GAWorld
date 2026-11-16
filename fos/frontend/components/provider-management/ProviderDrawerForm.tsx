// frontend/components/provider-management/ProviderDrawerForm.tsx
//
// This file shows the side panel (drawer) used to add or change an LLM provider.
// It renders the form fields and a small "provider type" chooser.
// The panel closes only when a person presses and releases on the dark area
// around it. Selecting text inside the panel and dragging the mouse out no
// longer closes it by mistake.
import { useEffect, useRef, useState, type MouseEvent } from "react";
import { ChevronDown, Eye, EyeOff, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Provider } from "../../services/providers";
import type { ProviderFormValues } from "./ProviderManagementPage";

type ProviderDrawerFormProps = {
  isOpen: boolean;
  mode: "create" | "edit";
  provider: Provider | null;
  initialValues: ProviderFormValues;
  onClose: () => void;
  onSubmit: (values: ProviderFormValues) => void;
  isSaving: boolean;
};

type ProviderPickerStep = "closed" | "type" | "compatible";

const COMPATIBLE_PROVIDERS = ["chatgpt", "deepseek", "minimax", "kimi"] as const;

const PROVIDER_LABEL_KEYS: Record<(typeof COMPATIBLE_PROVIDERS)[number], string> = {
  chatgpt: "settings.providers.compatibleProvider.chatgpt",
  deepseek: "settings.providers.compatibleProvider.deepseek",
  minimax: "settings.providers.compatibleProvider.minimax",
  kimi: "settings.providers.compatibleProvider.kimi",
};

export function ProviderDrawerForm({
  isOpen,
  mode,
  provider,
  initialValues,
  onClose,
  onSubmit,
  isSaving,
}: ProviderDrawerFormProps) {
  const { t } = useTranslation();
  const [values, setValues] = useState<ProviderFormValues>(initialValues);
  const [showApiKey, setShowApiKey] = useState(false);
  const [providerPickerStep, setProviderPickerStep] = useState<ProviderPickerStep>("closed");

  // Remembers whether the current press began on the dark area around the panel.
  const pressStartedOnBackdrop = useRef(false);

  // Notes where a press started so a text selection begun inside the panel is respected.
  const handleBackdropMouseDown = (event: MouseEvent<HTMLDivElement>): void => {
    pressStartedOnBackdrop.current = event.target === event.currentTarget;
  };

  // Closes the panel only when the press starts and ends on the dark area around it.
  const handleBackdropMouseUp = (event: MouseEvent<HTMLDivElement>): void => {
    const releasedOnBackdrop = event.target === event.currentTarget;
    if (pressStartedOnBackdrop.current && releasedOnBackdrop) {
      onClose();
    }
    pressStartedOnBackdrop.current = false;
  };

  useEffect(() => {
    setValues(initialValues);
    setShowApiKey(false);
    setProviderPickerStep("closed");
  }, [initialValues, isOpen]);

  if (!isOpen) return null;

  const title =
    mode === "create"
      ? t("settings.providers.providerForm.newLlmTitle")
      : t("settings.providers.providerForm.editLlmTitle", { name: provider?.name ?? "" });

  return (
    <div
      className="provider-drawer-shell"
      role="presentation"
      onMouseDown={handleBackdropMouseDown}
      onMouseUp={handleBackdropMouseUp}
    >
      <aside className="provider-drawer" role="dialog" aria-modal="true">
        <div className="provider-drawer__header">
          <div>
            <h2 className="provider-drawer__title">{title}</h2>
            <p className="provider-drawer__subtitle">{t("settings.providers.providerForm.openaiCompatibleAccessConfig")}</p>
          </div>
          <button type="button" className="provider-drawer__close" onClick={onClose} aria-label={t("common.cancel")}>
            <X size={18} />
          </button>
        </div>

        <form
          className="provider-drawer__form"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit(values);
          }}
        >
          <div className="provider-form-grid">
            <label className="provider-field">
              <span className="provider-field__label">{t("settings.providers.providerForm.llmNameRequired")}</span>
              <input
                className="provider-field__input"
                value={values.name}
                onChange={(event) => setValues((current) => ({ ...current, name: event.target.value }))}
                placeholder={t("settings.providers.providerForm.llmNamePlaceholder")}
                required
              />
            </label>

            <div className="provider-field">
              <span className="provider-field__label">{t("settings.providers.providerForm.providerTypeRequired")}</span>
              <div className="provider-type-picker">
                <button
                  type="button"
                  className="provider-field__input provider-type-picker__trigger"
                  aria-label={t("settings.providers.providerForm.providerTypeRequired")}
                  aria-expanded={providerPickerStep !== "closed"}
                  onClick={() => setProviderPickerStep("type")}
                >
                  <span>
                    {values.provider === "custom"
                      ? t("settings.providers.type.other")
                      : values.compatible_provider
                        ? t(PROVIDER_LABEL_KEYS[values.compatible_provider])
                        : t("settings.providers.type.openai")}
                  </span>
                  <ChevronDown size={16} aria-hidden="true" />
                </button>

                {providerPickerStep === "type" ? (
                  <div className="provider-type-picker__menu" role="listbox" aria-label={t("settings.providers.providerForm.providerTypeRequired")}>
                    <button type="button" className="provider-type-picker__option" role="option" onClick={() => setProviderPickerStep("compatible")}>
                      {t("settings.providers.type.openai")}
                    </button>
                    <button
                      type="button"
                      className="provider-type-picker__option"
                      role="option"
                      onClick={() => {
                        setValues((current) => ({ ...current, provider: "custom", compatible_provider: "" }));
                        setProviderPickerStep("closed");
                      }}
                    >
                      {t("settings.providers.type.other")}
                    </button>
                  </div>
                ) : null}

                {providerPickerStep === "compatible" ? (
                  <div
                    className="provider-type-picker__menu"
                    role="listbox"
                    aria-label={t("settings.providers.providerForm.openaiCompatibleProviders")}
                  >
                    {COMPATIBLE_PROVIDERS.map((compatibleProvider) => (
                      <button
                        key={compatibleProvider}
                        type="button"
                        className="provider-type-picker__option"
                        role="option"
                        onClick={() => {
                          setValues((current) => ({ ...current, provider: "openai-compatible", compatible_provider: compatibleProvider }));
                          setProviderPickerStep("closed");
                        }}
                      >
                        {t(PROVIDER_LABEL_KEYS[compatibleProvider])}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>

            <label className="provider-field provider-field--full">
              <span className="provider-field__label">{t("settings.providers.providerForm.baseUrlRequired")}</span>
              <input
                className="provider-field__input"
                value={values.base_url}
                onChange={(event) => setValues((current) => ({ ...current, base_url: event.target.value }))}
                placeholder={t("settings.providers.providerForm.baseUrlPlaceholder")}
                required
              />
            </label>

            <label className="provider-field provider-field--full">
              <span className="provider-field__label">{t("settings.providers.providerForm.apiKeyRequired")}</span>
              <div className="provider-field__secret-row">
                <input
                  className="provider-field__input"
                  type={showApiKey ? "text" : "password"}
                  value={values.api_key}
                  onChange={(event) => setValues((current) => ({ ...current, api_key: event.target.value }))}
                  placeholder={t("settings.providers.providerForm.apiKeyPlaceholder")}
                  required={false}
                />
                <button
                  type="button"
                  className="provider-field__secret-toggle"
                  onClick={() => setShowApiKey((current) => !current)}
                  aria-label={
                    showApiKey
                      ? t("settings.providers.providerForm.hideApiKey")
                      : t("settings.providers.providerForm.showApiKey")
                  }
                >
                  {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>

            <label className="provider-field provider-field--full">
              <span className="provider-field__label">{t("settings.providers.providerForm.defaultModel")}</span>
              <input
                className="provider-field__input"
                value={values.model}
                onChange={(event) => setValues((current) => ({ ...current, model: event.target.value }))}
                placeholder={t("settings.providers.providerForm.defaultModelPlaceholderOpenai")}
              />
            </label>
          </div>

          <details className="provider-advanced">
            <summary className="provider-advanced__summary">{t("settings.providers.providerForm.advancedSettings")}</summary>
            <div className="provider-advanced__body">
              <div className="provider-advanced__grid">
                <label className="provider-field">
                  <span className="provider-field__label">{t("settings.providers.providerForm.temperature")}</span>
                  <input
                    className="provider-field__input"
                    value={values.temperature}
                    onChange={(event) => setValues((current) => ({ ...current, temperature: event.target.value }))}
                    placeholder={t("settings.providers.providerForm.exampleDecimal07")}
                    inputMode="decimal"
                  />
                </label>

                <label className="provider-field">
                  <span className="provider-field__label">{t("settings.providers.providerForm.topP")}</span>
                  <input
                    className="provider-field__input"
                    value={values.top_p}
                    onChange={(event) => setValues((current) => ({ ...current, top_p: event.target.value }))}
                    placeholder={t("settings.providers.providerForm.exampleDecimal10")}
                    inputMode="decimal"
                  />
                </label>

                <label className="provider-field">
                  <span className="provider-field__label">{t("settings.providers.providerForm.maxTokens")}</span>
                  <input
                    className="provider-field__input"
                    value={values.max_tokens}
                    onChange={(event) => setValues((current) => ({ ...current, max_tokens: event.target.value }))}
                    placeholder={t("settings.providers.providerForm.exampleMaxTokens")}
                    inputMode="numeric"
                  />
                </label>

                <label className="provider-field">
                  <span className="provider-field__label">{t("settings.providers.providerForm.responseFormat")}</span>
                  <input
                    className="provider-field__input"
                    value={values.response_format}
                    onChange={(event) => setValues((current) => ({ ...current, response_format: event.target.value }))}
                    placeholder={t("settings.providers.providerForm.exampleJsonObject")}
                  />
                </label>

                <label className="provider-field provider-field--full">
                  <span className="provider-field__label">{t("settings.providers.providerForm.timeoutMs")}</span>
                  <input
                    className="provider-field__input"
                    value={values.timeout_ms}
                    onChange={(event) => setValues((current) => ({ ...current, timeout_ms: event.target.value }))}
                    placeholder={t("settings.providers.providerForm.exampleTimeoutMs")}
                    inputMode="numeric"
                  />
                </label>
              </div>

              <label className="provider-field provider-field--full">
                <span className="provider-field__label">{t("settings.providers.providerForm.customEndpoint")}</span>
                <input
                  className="provider-field__input"
                  value={values.custom_endpoint}
                  onChange={(event) => setValues((current) => ({ ...current, custom_endpoint: event.target.value }))}
                  placeholder={t("settings.providers.providerForm.optional")}
                />
              </label>

              <label className="provider-field provider-field--full">
                <span className="provider-field__label">{t("settings.providers.providerForm.headersMetadata")}</span>
                <textarea
                  className="provider-field__textarea"
                  value={values.metadata}
                  onChange={(event) => setValues((current) => ({ ...current, metadata: event.target.value }))}
                  placeholder={t("settings.providers.providerForm.optional")}
                  rows={4}
                />
              </label>

              <p className="provider-advanced__hint">{t("settings.providers.providerForm.advancedHint")}</p>
            </div>
          </details>

          <div className="provider-drawer__footer">
            <button type="button" className="provider-button provider-button--ghost" onClick={onClose}>
              {t("common.cancel")}
            </button>
            <button type="submit" className="provider-button provider-button--primary" disabled={isSaving}>
              {isSaving ? t("settings.providers.providerForm.saving") : t("settings.providers.providerForm.save")}
            </button>
          </div>
        </form>
      </aside>
    </div>
  );
}
