/**
 * Tests for SimTree translation key existence.
 *
 * Verifies that all SimTree translation keys exist in both
 * English and Chinese locale files with matching structure.
 *
 * Exports: None (test file)
 */

import { describe, it, expect } from 'vitest';
import en from '../../locales/en.json';
import zh from '../../locales/zh.json';

describe('SimTree translation keys', () => {
  const requiredKeys = [
    'title',
    'zoomIn',
    'zoomOut',
    'resetView',
    'legendHelp',
    'confirmDelete',
    'deleteNode',
    'selectCompareNode',
    'baseline',
    'compare',
    'clickToCompare',
    'frontier',
    'selected',
    'failed',
  ];

  it('all SimTree keys exist in English locale', () => {
    const simTreeKeys = (en as any).components.simTree;

    requiredKeys.forEach(key => {
      expect(simTreeKeys[key]).toBeDefined();
      expect(typeof simTreeKeys[key]).toBe('string');
      expect(simTreeKeys[key].length).toBeGreaterThan(0);
    });
  });

  it('all SimTree keys exist in Chinese locale', () => {
    const simTreeKeys = (zh as any).components.simTree;

    requiredKeys.forEach(key => {
      expect(simTreeKeys[key]).toBeDefined();
      expect(typeof simTreeKeys[key]).toBe('string');
      expect(simTreeKeys[key].length).toBeGreaterThan(0);
    });
  });

  it('English and Chinese keys have matching structure', () => {
    const enKeys = Object.keys((en as any).components.simTree).sort();
    const zhKeys = Object.keys((zh as any).components.simTree).sort();

    expect(enKeys).toEqual(zhKeys);
  });
});
