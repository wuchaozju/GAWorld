/**
 * This file contains strict i18n checks with low noise for CI gating.
 * flattenLocale turns nested locale objects into dotted keys for easy comparison.
 * extractVars reads interpolation variable names from translation strings.
 * walkSourceFiles finds frontend source files to scan for anti-patterns.
 * extractIsZhTernaries finds hardcoded bilingual ternaries that should use t().
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

function extractVars(value: string): string[] {
  return [...value.matchAll(/\{\{(\w+)\}\}/g)].map((match) => match[1]).sort();
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

function extractIsZhTernaries(source: string): Array<{ match: string; line: number }> {
  const results: Array<{ match: string; line: number }> = [];
  const lines = source.split('\n');
  lines.forEach((line, index) => {
    if (/isZh\s*\?/.test(line) && /['"][^'"]{3,}['"]/.test(line)) {
      if (!line.includes('t(') && !line.includes('className')) {
        results.push({ match: line.trim(), line: index + 1 });
      }
    }
  });
  return results;
}

const enFlat = flattenLocale(enLocale as Record<string, unknown>);
const zhFlat = flattenLocale(zhLocale as Record<string, unknown>);
const FRONTEND_DIR = join(__dirname, '..');
const SOURCE_FILES = walkSourceFiles(FRONTEND_DIR);

describe('Strict i18n parity checks', () => {
  it('all English keys exist in Chinese locale', () => {
    const missing = Object.keys(enFlat).filter((key) => !(key in zhFlat));
    expect(missing, `${missing.length} key(s) in en.json missing from zh.json:\n${missing.join('\n')}`).toHaveLength(0);
  });

  it('all Chinese keys exist in English locale', () => {
    const missing = Object.keys(zhFlat).filter((key) => !(key in enFlat));
    expect(missing, `${missing.length} key(s) in zh.json missing from en.json:\n${missing.join('\n')}`).toHaveLength(0);
  });

  it('no empty translation values in en.json', () => {
    const empty = Object.entries(enFlat).filter(([, value]) => value.trim() === '').map(([key]) => key);
    expect(empty, `${empty.length} empty value(s) in en.json:\n${empty.join('\n')}`).toHaveLength(0);
  });

  it('no empty translation values in zh.json', () => {
    const empty = Object.entries(zhFlat).filter(([, value]) => value.trim() === '').map(([key]) => key);
    expect(empty, `${empty.length} empty value(s) in zh.json:\n${empty.join('\n')}`).toHaveLength(0);
  });

  it('interpolation variables match between en.json and zh.json', () => {
    const mismatches: string[] = [];
    for (const key of Object.keys(enFlat)) {
      if (!(key in zhFlat)) continue;
      const enVars = extractVars(enFlat[key]);
      const zhVars = extractVars(zhFlat[key]);
      const enSet = new Set(enVars);
      const zhSet = new Set(zhVars);
      const missingInZh = enVars.filter((v) => !zhSet.has(v));
      const extraInZh = zhVars.filter((v) => !enSet.has(v));
      if (missingInZh.length > 0 || extraInZh.length > 0) {
        mismatches.push(
          `  ${key}\n` +
            (missingInZh.length ? `    missing in zh: {{${missingInZh.join('}}, {{')}}}\n` : '') +
            (extraInZh.length ? `    extra in zh: {{${extraInZh.join('}}, {{')}}}\n` : '')
        );
      }
    }
    expect(mismatches, `${mismatches.length} key(s) with interpolation mismatch:\n${mismatches.join('\n')}`).toHaveLength(0);
  });
});

describe('Strict i18n anti-pattern checks', () => {
  it('no components use isZh ternaries for UI text', () => {
    const violations: string[] = [];
    for (const file of SOURCE_FILES) {
      if (!file.endsWith('.tsx')) continue;
      const source = readFileSync(file, 'utf-8');
      const ternaries = extractIsZhTernaries(source);
      for (const { match, line } of ternaries) {
        const rel = file.replace(`${FRONTEND_DIR}/`, '');
        violations.push(`  ${rel}:${line}\n    ${match.slice(0, 120)}`);
      }
    }
    expect(violations, `${violations.length} isZh ternary anti-pattern(s) found:\n${violations.join('\n')}`).toHaveLength(0);
  });
});
