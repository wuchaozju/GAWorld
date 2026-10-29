/**
 * frontend/__tests__/i18n.comprehensive.test.ts
 * ==============================================
 * Comprehensive frontend i18n tests for FOS.
 *
 * Covers violation categories found in this codebase:
 *
 *   1. TERNARY ANTI-PATTERN  isZh ? "中文" : "English"  (must use t())
 *   2. t() KEYS MISSING from en.json or zh.json (silent fallback to key string)
 *   3. LOCALE KEY PARITY  — en.json ↔ zh.json must match
 *   4. INTERPOLATION PARITY — {{var}} names must match across locales
 *   5. CHINESE LOCALE VALUES must contain Chinese characters
 *   6. DESIGN.TS PARITY between enDesign and zhDesign
 *   7. JSX HARDCODED TEXT between JSX tags (must use {t(...)})
 *   8. ARIA LABEL HARDCODED VALUES (must use aria-label={t(...)})
 *
 * Run with:
 *   npx vitest run __tests__/i18n.comprehensive.test.ts
 *
 * Add to CI (package.json):
 *   "test:i18n": "vitest run __tests__/i18n.comprehensive.test.ts"
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'fs';
import { join, extname } from 'path';
import enLocale from '../locales/en.json';
import zhLocale from '../locales/zh.json';

// ── Helpers ──────────────────────────────────────────────────────────────

/** Recursively flatten {a: {b: "val"}} → {"a.b": "val"} */
function flattenLocale(obj: Record<string, unknown>, prefix = ''): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
      Object.assign(result, flattenLocale(value as Record<string, unknown>, fullKey));
    } else {
      result[fullKey] = String(value ?? '');
    }
  }
  return result;
}

/** Extract {{variable}} names from a translation string */
function extractVars(s: string): string[] {
  return [...s.matchAll(/\{\{(\w+)\}\}/g)].map(m => m[1]).sort();
}

/** Walk directory and return all .tsx/.ts files (excluding node_modules, test files) */
function walkSourceFiles(dir: string): string[] {
  const files: string[] = [];
  try {
    for (const entry of readdirSync(dir)) {
      if (entry === 'node_modules' || entry === '__tests__' || entry === 'test-utils') continue;
      const full = join(dir, entry);
      const stat = statSync(full);
      if (stat.isDirectory()) {
        files.push(...walkSourceFiles(full));
      } else if (['.tsx', '.ts'].includes(extname(entry)) && !entry.endsWith('.test.ts') && !entry.endsWith('.test.tsx') && !entry.endsWith('.spec.ts')) {
        files.push(full);
      }
    }
  } catch {}
  return files;
}

/** Extract all t("key") / t('key') calls from source text */
function extractTKeys(source: string): string[] {
  const keys: string[] = [];
  // Matches: t("key"), t('key'), t(`key`) — but NOT inside comments
  const re = /\bt\(\s*['"`]([^'"`\n]+)['"`]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source)) !== null) {
    const key = m[1];
    // Skip dynamic template-literal keys (contain ${...}) — resolved at runtime
    if (key.includes('${')) continue;
    // Filter out strings that look like sentences (have spaces and start with uppercase)
    // We only want dotted/underscored i18n keys
    if (key.includes('.') || key.includes('_')) {
      keys.push(key);
    }
  }
  return keys;
}

/** Extract isZh ternary patterns — the anti-pattern this codebase uses */
function extractIsZhTernaries(source: string): Array<{ match: string; line: number }> {
  const results: Array<{ match: string; line: number }> = [];
  const lines = source.split('\n');
  lines.forEach((line, i) => {
    // Matches: isZh ? "..." : "..."  or  isZh ? '...' : '...'
    if (/isZh\s*\?/.test(line) && /['"][^'"]{3,}['"]/.test(line)) {
      // Skip if it's already using t() or is a variable/class name comparison
      if (!line.includes('t(') && !line.includes('className')) {
        results.push({ match: line.trim(), line: i + 1 });
      }
    }
  });
  return results;
}

// ── Pre-load flattened locales ────────────────────────────────────────────
const enFlat = flattenLocale(enLocale as Record<string, unknown>);
const zhFlat = flattenLocale(zhLocale as Record<string, unknown>);

// ── Locate source files ───────────────────────────────────────────────────
// Adjust path if running from different working directory
const FRONTEND_DIR = join(__dirname, '..');
const SOURCE_FILES = walkSourceFiles(FRONTEND_DIR);


// ═══════════════════════════════════════════════════════════════════════════
// TEST SUITE 1: isZh ternary anti-pattern
// ═══════════════════════════════════════════════════════════════════════════

describe('Anti-pattern: isZh ternary (must use t())', () => {
  /**
   * WHY: The pattern  isZh ? "中文字符串" : "English string"
   * hardcodes both languages inline. This:
   *   - Bypasses the translation system
   *   - Cannot be audited or maintained from locale files
   *   - Will break if a third language is ever added
   *   - Means the string doesn't appear in en.json/zh.json at all
   *
   * FIX: Replace  isZh ? "快照管理" : "Snapshot manager"
   *        with  t('snapshotModal.title')
   * and add  snapshotModal.title  to both locale JSON files.
   */
  it('no components use isZh ternaries for UI text', () => {
    const violations: string[] = [];

    for (const file of SOURCE_FILES) {
      if (!file.endsWith('.tsx')) continue;
      const source = readFileSync(file, 'utf-8');
      const ternaries = extractIsZhTernaries(source);
      for (const { match, line } of ternaries) {
        const rel = file.replace(FRONTEND_DIR + '/', '');
        violations.push(`  ${rel}:${line}\n    ${match.slice(0, 120)}`);
      }
    }

    expect(violations, [
      `${violations.length} isZh ternary anti-pattern(s) found.`,
      'Replace all  isZh ? "中文" : "English"  with  t("locale.key").',
      'Add the key to both frontend/locales/en.json and zh.json.',
      '',
      ...violations,
    ].join('\n')).toHaveLength(0);
  });

  it('SnapshotModal has no isZh ternaries', () => {
    // Targeted test for the worst offender identified in audit
    const file = join(FRONTEND_DIR, 'components', 'SnapshotModal.tsx');
    let source = '';
    try { source = readFileSync(file, 'utf-8'); } catch { return; }
    const ternaries = extractIsZhTernaries(source);
    expect(ternaries.map(t => t.match), 'SnapshotModal.tsx still uses isZh ternaries').toHaveLength(0);
  });

  it('AdvancedTreeOpsModal has no isZh ternaries', () => {
    const file = join(FRONTEND_DIR, 'components', 'AdvancedTreeOpsModal.tsx');
    let source = '';
    try { source = readFileSync(file, 'utf-8'); } catch { return; }
    const ternaries = extractIsZhTernaries(source);
    expect(ternaries.map(t => t.match), 'AdvancedTreeOpsModal.tsx still uses isZh ternaries').toHaveLength(0);
  });
});


// ═══════════════════════════════════════════════════════════════════════════
// TEST SUITE 2: t() keys must exist in locale files
// ═══════════════════════════════════════════════════════════════════════════

describe('t() keys must exist in locale files', () => {
  /**
   * WHY: When react-i18next can't find a key it renders the key string
   * itself (e.g. "components.agentPanel.activeNow") as visible text.
   * This is a silent failure — no error is thrown.
   *
   * This codebase has 222 t() calls referencing keys that don't exist
   * in en.json yet. The most common are:
   *   common.actions, common.close, common.status, common.remove
   *   components.agentPanel.*, components.hostPanel.*, components.exportModal.*
   */
  it('all t() keys used in source exist in en.json', () => {
    const missing: string[] = [];

    for (const file of SOURCE_FILES) {
      const source = readFileSync(file, 'utf-8');
      const keys = extractTKeys(source);
      for (const key of keys) {
        if (!(key in enFlat)) {
          const rel = file.replace(FRONTEND_DIR + '/', '');
          missing.push(`  ${key}  (used in ${rel})`);
        }
      }
    }

    // Deduplicate
    const unique = [...new Set(missing)].sort();
    expect(unique, [
      `${unique.length} t() key(s) used in source are missing from en.json:`,
      '',
      ...unique,
      '',
      'Add these keys to frontend/locales/en.json.',
    ].join('\n')).toHaveLength(0);
  });

  it('all t() keys used in source exist in zh.json', () => {
    const missing: string[] = [];

    for (const file of SOURCE_FILES) {
      const source = readFileSync(file, 'utf-8');
      const keys = extractTKeys(source);
      for (const key of keys) {
        if (!(key in zhFlat)) {
          const rel = file.replace(FRONTEND_DIR + '/', '');
          missing.push(`  ${key}  (used in ${rel})`);
        }
      }
    }

    const unique = [...new Set(missing)].sort();
    expect(unique, [
      `${unique.length} t() key(s) used in source are missing from zh.json:`,
      '',
      ...unique,
      '',
      'Add these keys to frontend/locales/zh.json.',
    ].join('\n')).toHaveLength(0);
  });
});


// ═══════════════════════════════════════════════════════════════════════════
// TEST SUITE 3: Locale key parity
// ═══════════════════════════════════════════════════════════════════════════

describe('Locale file parity (en.json ↔ zh.json)', () => {
  it('all English keys exist in Chinese locale', () => {
    const missing = Object.keys(enFlat).filter(k => !(k in zhFlat));
    expect(missing, [
      `${missing.length} key(s) in en.json missing from zh.json:`,
      ...missing.sort().map(k => `  ${k}`),
    ].join('\n')).toHaveLength(0);
  });

  it('all Chinese keys exist in English locale', () => {
    const missing = Object.keys(zhFlat).filter(k => !(k in enFlat));
    expect(missing, [
      `${missing.length} key(s) in zh.json missing from en.json:`,
      ...missing.sort().map(k => `  ${k}`),
    ].join('\n')).toHaveLength(0);
  });

  it('no empty translation values in en.json', () => {
    const empty = Object.entries(enFlat).filter(([, v]) => v.trim() === '').map(([k]) => k);
    expect(empty, `${empty.length} empty value(s) in en.json:\n${empty.join('\n')}`).toHaveLength(0);
  });

  it('no empty translation values in zh.json', () => {
    const empty = Object.entries(zhFlat).filter(([, v]) => v.trim() === '').map(([k]) => k);
    expect(empty, `${empty.length} empty value(s) in zh.json:\n${empty.join('\n')}`).toHaveLength(0);
  });
});


// ═══════════════════════════════════════════════════════════════════════════
// TEST SUITE 4: Interpolation variable parity
// ═══════════════════════════════════════════════════════════════════════════

describe('Interpolation variable parity ({{var}} must match)', () => {
  /**
   * WHY: If en.json has "{{agent}} chose {{action}}" but zh.json has
   * "{{agent}}选择了动作" (missing {{action}}), the Chinese output won't
   * show the action name — a silent data loss.
   *
   * NOTE: This codebase uses {{var}} (double-brace) in frontend locale files
   * and {var} (single-brace) in Python backend locale files.
   */
  it('{{variable}} names match between en.json and zh.json for every key', () => {
    const mismatches: string[] = [];

    for (const key of Object.keys(enFlat)) {
      if (!(key in zhFlat)) continue;
      const enVars = extractVars(enFlat[key]);
      const zhVars = extractVars(zhFlat[key]);

      const enSet = new Set(enVars);
      const zhSet = new Set(zhVars);
      const missingInZh = enVars.filter(v => !zhSet.has(v));
      const extraInZh   = zhVars.filter(v => !enSet.has(v));

      if (missingInZh.length > 0 || extraInZh.length > 0) {
        mismatches.push(
          `  ${key}\n` +
          (missingInZh.length ? `    missing in zh: {{${missingInZh.join('}}, {{')}}}\n` : '') +
          (extraInZh.length   ? `    extra in zh:   {{${extraInZh.join('}}, {{')}}}\n` : '')
        );
      }
    }

    expect(mismatches, [
      `${mismatches.length} key(s) have mismatched interpolation variables:`,
      '',
      ...mismatches,
    ].join('\n')).toHaveLength(0);
  });
});


// ═══════════════════════════════════════════════════════════════════════════
// TEST SUITE 5: zh.json values must contain Chinese characters
// ═══════════════════════════════════════════════════════════════════════════

describe('zh.json values must be Chinese (not untranslated English)', () => {
  /**
   * WHY: A zh.json entry that is plain English is an untranslated copy-paste.
   * Chinese users will see English text for that string.
   *
   * Keys intentionally in English (brand names, etc.) are whitelisted below.
   */
  const ZH_ENGLISH_OK = new Set([
    'brand',
    'landing.hero.line1',   // "Future of Society" brand tagline
    'landing.hero.line2',
    'landing.hero.accent',
    'auth.login.badge',     // "Social Systems Laboratory" — proper noun / brand
    'components.initialEventsModal.audioUrlPlaceholder', // URL placeholder
    'components.initialEventsModal.videoUrlPlaceholder', // URL placeholder
  ]);

  const ZH_CHAR_RE = /[\u4e00-\u9fff]/;
  const EN_WORD_RE = /\b[a-zA-Z]{4,}\b/g;

  it('all zh.json values contain Chinese characters (or are whitelisted)', () => {
    const suspicious: string[] = [];

    for (const [key, value] of Object.entries(zhFlat)) {
      if (ZH_ENGLISH_OK.has(key)) continue;
      if (value.trim().length < 5) continue;

      // Remove interpolation placeholders before checking
      const textOnly = value.replace(/\{\{[^}]+\}\}/g, '').trim();
      if (!textOnly) continue;

      const enWords = (textOnly.match(EN_WORD_RE) || []).length;
      const hasZh   = ZH_CHAR_RE.test(textOnly);

      if (enWords >= 3 && !hasZh) {
        suspicious.push(`  ${key}: "${value.slice(0, 80)}"`);
      }
    }

    expect(suspicious, [
      `${suspicious.length} zh.json value(s) appear untranslated (English text, no Chinese characters):`,
      ...suspicious,
    ].join('\n')).toHaveLength(0);
  });
});


// ═══════════════════════════════════════════════════════════════════════════
// TEST SUITE 6: design.ts locale completeness
// ═══════════════════════════════════════════════════════════════════════════

describe('design.ts locale completeness', () => {
  /**
   * design.ts exports enDesign and zhDesign which are merged into the main
   * locale at startup. They must have matching keys.
   */
  it('enDesign and zhDesign have the same keys', async () => {
    let enDesign: Record<string, unknown> = {};
    let zhDesign: Record<string, unknown> = {};
    try {
      const mod = await import('../locales/design');
      enDesign = mod.enDesign as Record<string, unknown>;
      zhDesign = mod.zhDesign as Record<string, unknown>;
    } catch {
      // If design.ts can't be imported, skip
      return;
    }

    const enKeys = new Set(Object.keys(flattenLocale(enDesign)));
    const zhKeys = new Set(Object.keys(flattenLocale(zhDesign)));

    const missingZh = [...enKeys].filter(k => !zhKeys.has(k));
    const missingEn = [...zhKeys].filter(k => !enKeys.has(k));

    expect([...missingZh, ...missingEn], [
      'design.ts: enDesign and zhDesign have different keys.',
      missingZh.length ? `Missing in zhDesign: ${missingZh.join(', ')}` : '',
      missingEn.length ? `Missing in enDesign: ${missingEn.join(', ')}` : '',
    ].filter(Boolean).join('\n')).toHaveLength(0);
  });
});


// ═══════════════════════════════════════════════════════════════════════════
// TEST SUITE 7: JSX hardcoded text detection
// ═══════════════════════════════════════════════════════════════════════════

describe('JSX hardcoded text detection', () => {
  /**
   * WHY: Text hardcoded directly in JSX (e.g. <div>Hello World</div>) bypasses
   * the translation system entirely. It will always appear in the hardcoded
   * language regardless of the user's locale setting.
   *
   * FIX: Replace  <div>Hello World</div>
   *        with  <div>{t('some.key')}</div>
   * and add the key to both locale files.
   */
  it('no .tsx files have hardcoded UI text between JSX tags', () => {
    const violations: string[] = [];
    const componentsDir = join(FRONTEND_DIR, 'components');
    const tsxFiles = walkSourceFiles(componentsDir).filter(f => f.endsWith('.tsx'));

    for (const file of tsxFiles) {
      const source = readFileSync(file, 'utf-8');
      const lines = source.split('\n');
      const rel = file.replace(FRONTEND_DIR + '/', '');

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trimStart();

        // Skip comment lines
        if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) continue;

        // Find text between JSX tags: >TEXTCONTENT<
        // [^<{] excludes expressions {t(...)} and nested tags
        const jsxTextRe = />\s*([A-Z][^<{]*?)\s*</g;
        let m: RegExpExecArray | null;
        while ((m = jsxTextRe.exec(line)) !== null) {
          const text = m[1].trim();
          // Must be longer than 4 characters
          if (text.length <= 4) continue;
          violations.push(`  ${rel}:${i + 1}\n    "${text}"`);
        }
      }
    }

    expect(violations, [
      `${violations.length} hardcoded JSX text violation(s) found.`,
      'Replace hardcoded text with {t("locale.key")} calls.',
      'Add the key to both frontend/locales/en.json and zh.json.',
      '',
      ...violations,
    ].join('\n')).toHaveLength(0);
  });
});


// ═══════════════════════════════════════════════════════════════════════════
// TEST SUITE 8: ARIA label hardcoded text detection
// ═══════════════════════════════════════════════════════════════════════════

describe('ARIA label hardcoded text detection', () => {
  /**
   * WHY: aria-label values that are plain strings (e.g. aria-label="Close dialog")
   * are not translated. Screen readers will read the hardcoded language to all users.
   *
   * FIX: Replace  aria-label="Close dialog"
   *        with  aria-label={t('a11y.closeDialog')}
   * and add the key to both locale files.
   */
  it('no .tsx files have hardcoded aria-label values', () => {
    const violations: string[] = [];
    const componentsDir = join(FRONTEND_DIR, 'components');
    const tsxFiles = walkSourceFiles(componentsDir).filter(f => f.endsWith('.tsx'));

    for (const file of tsxFiles) {
      const source = readFileSync(file, 'utf-8');
      const lines = source.split('\n');
      const rel = file.replace(FRONTEND_DIR + '/', '');

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trimStart();

        // Skip comment lines
        if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) continue;

        // Find aria-label="..." or aria-label='...' with plain string value
        // (aria-label={t(...)} uses curly braces and won't match)
        const ariaRe = /aria-label\s*=\s*(?:"([^"]+)"|'([^']+)')/g;
        let m: RegExpExecArray | null;
        while ((m = ariaRe.exec(line)) !== null) {
          const value = m[1] ?? m[2];
          // Skip values 2 chars or less
          if (value.length <= 2) continue;
          // Skip single words that look like code identifiers (lowercase, digits, hyphens, underscores)
          if (/^[a-z][a-z0-9_-]*$/.test(value)) continue;
          violations.push(`  ${rel}:${i + 1}\n    aria-label="${value}"`);
        }
      }
    }

    expect(violations, [
      `${violations.length} hardcoded aria-label violation(s) found.`,
      'Replace with aria-label={t("locale.key")} and add the key to both locale files.',
      '',
      ...violations,
    ].join('\n')).toHaveLength(0);
  });
});
