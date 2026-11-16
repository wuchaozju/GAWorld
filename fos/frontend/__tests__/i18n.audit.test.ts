/**
 * This file contains broad i18n audit checks for finding likely hardcoded text.
 * flattenLocale turns nested locale objects into dotted keys for key lookup.
 * walkSourceFiles finds source files to scan with regex-based heuristics.
 * extractTKeys finds translation keys used in code.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'fs';
import { join, extname } from 'path';
import enLocale from '../locales/en.json';
import zhLocale from '../locales/zh.json';

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

function walkSourceFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === '__tests__' || entry === 'test-utils') continue;
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      files.push(...walkSourceFiles(full));
    } else if (
      ['.tsx', '.ts'].includes(extname(entry)) &&
      !entry.endsWith('.test.ts') &&
      !entry.endsWith('.test.tsx') &&
      !entry.endsWith('.spec.ts')
    ) {
      files.push(full);
    }
  }
  return files;
}

function extractTKeys(source: string): string[] {
  const keys: string[] = [];
  const pattern = /\bt\(\s*['"`]([^'"`\n]+)['"`]/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(source)) !== null) {
    const key = match[1];
    // Skip dynamic template-literal keys (contain ${...}) — resolved at runtime
    if (key.includes('${')) continue;
    if (key.includes('.') || key.includes('_')) {
      keys.push(key);
    }
  }
  return keys;
}

const enFlat = flattenLocale(enLocale as Record<string, unknown>);
const zhFlat = flattenLocale(zhLocale as Record<string, unknown>);
const FRONTEND_DIR = join(__dirname, '..');
const SOURCE_FILES = walkSourceFiles(FRONTEND_DIR);

describe('Audit: t() keys should exist in locale files', () => {
  it('all t() keys used in source exist in en.json', () => {
    const missing: string[] = [];
    for (const file of SOURCE_FILES) {
      const source = readFileSync(file, 'utf-8');
      for (const key of extractTKeys(source)) {
        if (!(key in enFlat)) {
          const rel = file.replace(`${FRONTEND_DIR}/`, '');
          missing.push(`  ${key} (used in ${rel})`);
        }
      }
    }
    const unique = [...new Set(missing)].sort();
    expect(unique, `${unique.length} t() key(s) missing from en.json:\n${unique.join('\n')}`).toHaveLength(0);
  });

  it('all t() keys used in source exist in zh.json', () => {
    const missing: string[] = [];
    for (const file of SOURCE_FILES) {
      const source = readFileSync(file, 'utf-8');
      for (const key of extractTKeys(source)) {
        if (!(key in zhFlat)) {
          const rel = file.replace(`${FRONTEND_DIR}/`, '');
          missing.push(`  ${key} (used in ${rel})`);
        }
      }
    }
    const unique = [...new Set(missing)].sort();
    expect(unique, `${unique.length} t() key(s) missing from zh.json:\n${unique.join('\n')}`).toHaveLength(0);
  });
});

describe('Audit: zh.json values may be untranslated', () => {
  it('all zh.json values contain Chinese characters or are whitelisted', () => {
    const allowedEnglish = new Set(['brand', 'landing.hero.line1', 'landing.hero.line2', 'landing.hero.accent', 'auth.login.badge', 'components.initialEventsModal.audioUrlPlaceholder', 'components.initialEventsModal.videoUrlPlaceholder']);
    const zhChars = /[\u4e00-\u9fff]/;
    const englishWords = /\b[a-zA-Z]{4,}\b/g;
    const suspicious: string[] = [];

    for (const [key, value] of Object.entries(zhFlat)) {
      if (allowedEnglish.has(key)) continue;
      if (value.trim().length < 5) continue;
      const textOnly = value.replace(/\{\{[^}]+\}\}/g, '').trim();
      if (!textOnly) continue;
      const enWordCount = (textOnly.match(englishWords) || []).length;
      const hasZh = zhChars.test(textOnly);
      if (enWordCount >= 3 && !hasZh) {
        suspicious.push(`  ${key}: "${value.slice(0, 80)}"`);
      }
    }

    expect(suspicious, `${suspicious.length} zh.json value(s) look untranslated:\n${suspicious.join('\n')}`).toHaveLength(0);
  });
});

describe('Audit: hardcoded JSX text detection', () => {
  it('no .tsx files have hardcoded UI text between JSX tags', () => {
    const violations: string[] = [];
    const componentsDir = join(FRONTEND_DIR, 'components');
    const tsxFiles = walkSourceFiles(componentsDir).filter((file) => file.endsWith('.tsx'));

    for (const file of tsxFiles) {
      const source = readFileSync(file, 'utf-8');
      const lines = source.split('\n');
      const rel = file.replace(`${FRONTEND_DIR}/`, '');
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trimStart();
        if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) continue;
        const jsxText = />\s*([A-Z][^<{]*?)\s*</g;
        let match: RegExpExecArray | null;
        while ((match = jsxText.exec(line)) !== null) {
          const text = match[1].trim();
          if (text.length <= 4) continue;
          violations.push(`  ${rel}:${i + 1}\n    "${text}"`);
        }
      }
    }

    expect(violations, `${violations.length} hardcoded JSX text violation(s):\n${violations.join('\n')}`).toHaveLength(0);
  });
});

describe('Audit: hardcoded aria-label detection', () => {
  it('no .tsx files have hardcoded aria-label values', () => {
    const violations: string[] = [];
    const componentsDir = join(FRONTEND_DIR, 'components');
    const tsxFiles = walkSourceFiles(componentsDir).filter((file) => file.endsWith('.tsx'));

    for (const file of tsxFiles) {
      const source = readFileSync(file, 'utf-8');
      const lines = source.split('\n');
      const rel = file.replace(`${FRONTEND_DIR}/`, '');
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trimStart();
        if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) continue;
        const ariaLabel = /aria-label\s*=\s*(?:"([^"]+)"|'([^']+)')/g;
        let match: RegExpExecArray | null;
        while ((match = ariaLabel.exec(line)) !== null) {
          const value = match[1] ?? match[2];
          if (value.length <= 2) continue;
          if (/^[a-z][a-z0-9_-]*$/.test(value)) continue;
          violations.push(`  ${rel}:${i + 1}\n    aria-label="${value}"`);
        }
      }
    }

    expect(violations, `${violations.length} hardcoded aria-label violation(s):\n${violations.join('\n')}`).toHaveLength(0);
  });
});
