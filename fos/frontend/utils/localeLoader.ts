/**
 * This file loads language files only when the app asks for them.
 * loadLocaleModule fetches one language and its matching design words.
 * getInitialLocaleModules fetches only the language needed for the first screen.
 * getSecondaryLocaleModules fetches both languages when the switcher later needs them.
 */

export type SupportedLanguage = "en" | "zh";

type LocaleMessages = typeof import("../locales/en.json");
type LocaleDesign = typeof import("../locales/design").enDesign;

export interface LocaleModule {
  language: SupportedLanguage;
  messages: LocaleMessages;
  design: LocaleDesign;
}

export interface InitialLocaleModules {
  active: LocaleModule;
  inactive: { language: SupportedLanguage };
}

export interface SecondaryLocaleModules {
  active: LocaleModule;
  inactive: LocaleModule;
}

function getOtherLanguage(language: SupportedLanguage): SupportedLanguage {
  return language === "en" ? "zh" : "en";
}

async function loadLocaleMessages(language: SupportedLanguage): Promise<LocaleMessages> {
  if (language === "zh") {
    const module = await import("../locales/zh.json");
    return module.default;
  }

  const module = await import("../locales/en.json");
  return module.default;
}

async function loadLocaleDesign(language: SupportedLanguage): Promise<LocaleDesign> {
  const module = await import("../locales/design");
  return language === "zh" ? module.zhDesign : module.enDesign;
}

export async function loadLocaleModule(language: SupportedLanguage): Promise<LocaleModule> {
  const [messages, design] = await Promise.all([
    loadLocaleMessages(language),
    loadLocaleDesign(language),
  ]);

  return { language, messages, design };
}

export async function getInitialLocaleModules(
  language: SupportedLanguage,
): Promise<InitialLocaleModules> {
  return {
    active: await loadLocaleModule(language),
    inactive: { language: getOtherLanguage(language) },
  };
}

export async function getSecondaryLocaleModules(
  language: SupportedLanguage,
): Promise<SecondaryLocaleModules> {
  const active = await loadLocaleModule(language);
  const inactive = await loadLocaleModule(getOtherLanguage(language));

  return { active, inactive };
}
