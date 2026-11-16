/**
 * Locale helper for E2E health-check tests.
 *
 * Loads i18n JSON files and provides a t() function for
 * locale-aware Playwright selectors. Supports English and Chinese.
 *
 * Exports: t, getLocaleText
 */

import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const LOCALES_DIR = path.resolve(__dirname, '../../locales');

type NestedRecord = { [key: string]: string | NestedRecord };

function loadLocale(locale: string): NestedRecord {
  const filePath = path.join(LOCALES_DIR, `${locale}.json`);
  return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
}

const cache: Record<string, NestedRecord> = {};

function getLocale(locale: string): NestedRecord {
  if (!cache[locale]) {
    cache[locale] = loadLocale(locale);
  }
  return cache[locale];
}

/**
 * Get translated text for a dot-notation i18n key.
 * Returns the key itself if not found.
 *
 * @param key - Dot-notation i18n key (e.g., 'simPage.advance')
 * @param locale - 'en' or 'zh'
 * @returns Translated string
 */
export function t(key: string, locale: string): string {
  const keys = key.split('.');
  let result: string | NestedRecord = getLocale(locale);

  for (const k of keys) {
    if (typeof result === 'object' && result !== null && k in result) {
      result = result[k];
    } else {
      return key; // Fallback to key
    }
  }

  return typeof result === 'string' ? result : key;
}

/**
 * Get the full locale object for direct access to nested translations.
 */
export function getLocaleText(locale: string): NestedRecord {
  return getLocale(locale);
}
