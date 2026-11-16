/**
 * Test utilities for i18n language switching.
 *
 * Provides helpers to switch languages in tests and verify
 * translation key behavior.
 *
 * Exports: switchLanguage, resetLanguage, getCurrentLanguage, waitForI18n
 */

import { vi } from 'vitest';

/**
 * Switch the i18n language for testing.
 * Updates the global i18n mock to use the specified language.
 *
 * @param lang - The language code ('en' or 'zh')
 */
export const switchLanguage = async (lang: 'en' | 'zh'): Promise<void> => {
  // Update the global i18n mock's language
  (globalThis as any).i18n.language = lang;
  // Wait for any pending updates
  await new Promise(resolve => setTimeout(resolve, 0));
};

/**
 * Reset the i18n language to English (default).
 */
export const resetLanguage = async (): Promise<void> => {
  (globalThis as any).i18n.language = 'en';
};

/**
 * Get the current language from the i18n mock.
 *
 * @returns The current language code
 */
export const getCurrentLanguage = (): string => {
  return (globalThis as any).i18n.language;
};

/**
 * Wait for i18n to be initialized.
 * In tests, this is a no-op since the mock is already initialized.
 */
export const waitForI18n = async (): Promise<void> => {
  // Mock i18n is always initialized in tests
  await new Promise(resolve => setTimeout(resolve, 0));
};
