/**
 * Shared language helper for API requests.
 *
 * Centralises the logic for determining the current UI language
 * so that the X-Language header stays consistent across all HTTP clients.
 * If a third language is ever added, this is the single place to update.
 *
 * Exports: getApiLanguage
 */
import i18n from '../i18n';

/**
 * Returns the two-character language code to send in the X-Language header.
 * Handles all zh variants (zh-CN, zh-TW, zh-Hant) by collapsing to "zh".
 */
export function getApiLanguage(): 'en' | 'zh' {
  return i18n.language?.startsWith('zh') ? 'zh' : 'en';
}
