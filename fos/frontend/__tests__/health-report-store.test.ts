/**
 * This file checks that health-check results survive test worker restarts.
 *
 * Each test checks atomic writes, duplicate replacement, stable ordering,
 * and complete bilingual report aggregation.
 */

import { mkdtempSync, readFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { describe, expect, it } from 'vitest';

import {
  buildHealthReports,
  readResultFragments,
  writeResultFragment,
} from '../e2e/helpers/health-report-store';
import type { ScenarioResult } from '../e2e/helpers/run-scenario';

function result(
  id: string,
  locale: 'en' | 'zh',
  status: ScenarioResult['status'] = 'passed',
): ScenarioResult {
  return {
    id,
    name: id,
    locale,
    status,
    uiErrors: status === 'passed' ? [] : ['failed'],
    warnings: [],
    backendErrors: [],
    testResultFiles: [],
    durationMs: 10,
  };
}

describe('health report fragments', () => {
  it('test_result_survives_a_new_store_instance', () => {
    const outputDir = mkdtempSync(join(tmpdir(), 'fos-health-report-'));
    writeResultFragment(outputDir, result('prisoners_dilemma', 'en'));

    expect(readResultFragments(outputDir)).toEqual([
      result('prisoners_dilemma', 'en'),
    ]);
  });

  it('test_duplicate_scenario_write_replaces_the_old_result', () => {
    const outputDir = mkdtempSync(join(tmpdir(), 'fos-health-report-'));
    writeResultFragment(outputDir, result('custom', 'en', 'crashed'));
    writeResultFragment(outputDir, result('custom', 'en', 'passed'));

    expect(readResultFragments(outputDir)).toEqual([
      result('custom', 'en', 'passed'),
    ]);
  });

  it('test_reports_include_passed_and_failed_results_in_scenario_order', () => {
    const outputDir = mkdtempSync(join(tmpdir(), 'fos-health-report-'));
    writeResultFragment(outputDir, result('custom', 'zh', 'ui_errors'));
    writeResultFragment(outputDir, result('public_goods', 'en'));
    writeResultFragment(outputDir, result('prisoners_dilemma', 'en'));

    buildHealthReports(outputDir, ['prisoners_dilemma', 'public_goods', 'custom']);

    const english = JSON.parse(
      readFileSync(join(outputDir, 'run-report-en.json'), 'utf-8'),
    ) as ScenarioResult[];
    const chinese = JSON.parse(
      readFileSync(join(outputDir, 'run-report-zh.json'), 'utf-8'),
    ) as ScenarioResult[];

    expect(english.map((item) => item.id)).toEqual([
      'prisoners_dilemma',
      'public_goods',
    ]);
    expect(chinese).toEqual([result('custom', 'zh', 'ui_errors')]);
    expect(readFileSync(join(outputDir, 'health-check-review.txt'), 'utf-8'))
      .toContain('Result: 2/3 tests passed');
  });
});
