import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import {
  getInitialLocaleModules,
  loadLocaleModule,
  type SupportedLanguage,
} from './utils/localeLoader';

const STORAGE_KEY = 'fos.lang';

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function mergeLocale(
  base: Record<string, unknown>,
  extension: Record<string, unknown>
): Record<string, unknown> {
  const merged: Record<string, unknown> = { ...base };

  Object.entries(extension).forEach(([key, value]) => {
    const current = merged[key];
    merged[key] =
      isRecord(current) && isRecord(value)
        ? mergeLocale(current, value)
        : value;
  });

  return merged;
}

function detectLanguage(): SupportedLanguage {
  const stored = typeof window !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null;
  if (stored === 'en' || stored === 'zh') return stored;
  if (typeof navigator !== 'undefined') {
    const nav = (navigator.language || navigator.languages?.[0] || 'en').toLowerCase();
    if (nav.startsWith('zh')) return 'zh';
  }
  return 'en';
}

async function ensureLanguageResources(lang: SupportedLanguage): Promise<void> {
  if (i18n.hasResourceBundle(lang, 'translation')) {
    return;
  }

  const localeModule = await loadLocaleModule(lang);
  i18n.addResourceBundle(
    lang,
    'translation',
    mergeLocale(
      localeModule.messages as Record<string, unknown>,
      localeModule.design as Record<string, unknown>,
    ),
    true,
    true,
  );
}

export async function setLanguage(lang: SupportedLanguage) {
  localStorage.setItem(STORAGE_KEY, lang);
  await ensureLanguageResources(lang);
  await i18n.changeLanguage(lang);
}

const initialLanguage = detectLanguage();
const i18nReady = (async () => {
  const initialLocaleModules = await getInitialLocaleModules(initialLanguage);

  await i18n
    .use(initReactI18next)
    .init({
      resources: {
        [initialLocaleModules.active.language]: {
          translation: mergeLocale(
            initialLocaleModules.active.messages as Record<string, unknown>,
            initialLocaleModules.active.design as Record<string, unknown>,
          ),
        },
      },
      lng: initialLanguage,
      fallbackLng: 'en',
      interpolation: { escapeValue: false },
    });

  ;(window as any).i18next = i18n;
})();

export function initializeI18n(): Promise<void> {
  return i18nReady;
}

export default i18n;
