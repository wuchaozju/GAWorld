/**
 * Comprehensive i18n validation tests.
 *
 * Verifies translation key parity between locale files and
 * ensures all keys have matching interpolation variables.
 */

import { describe, it, expect } from 'vitest';
import enLocale from '../../locales/en.json';
import zhLocale from '../../locales/zh.json';

// Recursively collect all keys from a locale object
function collectKeys(obj: any, prefix: string = ''): string[] {
  const keys: string[] = [];
  for (const key in obj) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (typeof obj[key] === 'object' && obj[key] !== null) {
      keys.push(...collectKeys(obj[key], fullKey));
    } else {
      keys.push(fullKey);
    }
  }
  return keys;
}

// Extract interpolation variables from a string
function extractVariables(str: string): string[] {
  const regex = /\{\{(\w+)\}\}/g;
  const variables: string[] = [];
  let match;
  while ((match = regex.exec(str)) !== null) {
    variables.push(match[1]);
  }
  return variables.sort();
}

describe('i18n validation', () => {
  it('all English keys exist in Chinese locale', () => {
    const enKeys = new Set(collectKeys(enLocale));
    const zhKeys = new Set(collectKeys(zhLocale));

    const missing = [...enKeys].filter(key => !zhKeys.has(key));

    expect(missing).toEqual([]);
  });

  it('all Chinese keys exist in English locale', () => {
    const enKeys = new Set(collectKeys(enLocale));
    const zhKeys = new Set(collectKeys(zhLocale));

    const missing = [...zhKeys].filter(key => !enKeys.has(key));

    expect(missing).toEqual([]);
  });

  it('interpolation variables match between EN and ZH', () => {
    const enKeys = collectKeys(enLocale);

    const mismatches: string[] = [];

    enKeys.forEach(key => {
      const enValue = key.split('.').reduce((obj: any, k) => obj?.[k], enLocale as any);
      const zhValue = key.split('.').reduce((obj: any, k) => obj?.[k], zhLocale as any);

      if (typeof enValue === 'string' && typeof zhValue === 'string') {
        const enVars = extractVariables(enValue);
        const zhVars = extractVariables(zhValue);

        if (enVars.length !== zhVars.length || !enVars.every((v, i) => v === zhVars[i])) {
          mismatches.push(`${key}: EN=${enVars.join(',')}, ZH=${zhVars.join(',')}`);
        }
      }
    });

    expect(mismatches).toEqual([]);
  });

  it('no empty translation values', () => {
    const enKeys = collectKeys(enLocale);
    const zhKeys = collectKeys(zhLocale);

    const emptyEn = enKeys.filter(key => {
      const value = key.split('.').reduce((obj: any, k) => obj?.[k], enLocale as any);
      return typeof value === 'string' && value.trim() === '';
    });

    const emptyZh = zhKeys.filter(key => {
      const value = key.split('.').reduce((obj: any, k) => obj?.[k], zhLocale as any);
      return typeof value === 'string' && value.trim() === '';
    });

    expect(emptyEn).toEqual([]);
    expect(emptyZh).toEqual([]);
  });
});
