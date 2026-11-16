/**
 * This file stores each health-check result independently and builds reports.
 *
 * writeResultFragment saves one result atomically.
 * readResultFragments reloads all saved results after worker restarts.
 * buildHealthReports creates bilingual JSON and readable review reports.
 */

import * as fs from 'fs';
import * as path from 'path';

import type { ScenarioResult } from './run-scenario';

const FRAGMENT_DIR = 'result-fragments';

function safeId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, '_');
}

export function writeResultFragment(
  outputDir: string,
  result: ScenarioResult,
  resultKey: string = result.id,
): void {
  const target = path.join(
    outputDir,
    FRAGMENT_DIR,
    `${safeId(result.locale)}-${safeId(resultKey)}.json`,
  );
  const temporary = `${target}.${process.pid}.tmp`;
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(temporary, JSON.stringify(result, null, 2));
  fs.renameSync(temporary, target);
}

export function readResultFragments(outputDir: string): ScenarioResult[] {
  const directory = path.join(outputDir, FRAGMENT_DIR);
  if (!fs.existsSync(directory)) return [];

  return fs.readdirSync(directory)
    .filter((name) => name.endsWith('.json'))
    .sort()
    .map((name) => JSON.parse(
      fs.readFileSync(path.join(directory, name), 'utf-8'),
    ) as ScenarioResult);
}

function sortResults(
  results: ScenarioResult[],
  scenarioOrder: string[],
): ScenarioResult[] {
  const order = new Map(scenarioOrder.map((id, index) => [id, index]));
  return [...results].sort((left, right) => {
    const leftOrder = order.get(left.id) ?? Number.MAX_SAFE_INTEGER;
    const rightOrder = order.get(right.id) ?? Number.MAX_SAFE_INTEGER;
    return leftOrder - rightOrder || left.id.localeCompare(right.id);
  });
}

function writeLocaleReport(
  outputDir: string,
  locale: 'en' | 'zh',
  results: ScenarioResult[],
): void {
  fs.writeFileSync(
    path.join(outputDir, `run-report-${locale}.json`),
    JSON.stringify(results, null, 2),
  );
}

function buildReview(results: ScenarioResult[]): string {
  const passed = results.filter((result) => result.status === 'passed').length;
  const lines = [
    '======================================================',
    'E2E Health-Check Review - All Scenarios (EN + ZH)',
    `Generated: ${new Date().toLocaleString()}`,
    `Result: ${passed}/${results.length} tests passed`,
    '======================================================',
    '',
    '## RUN REPORTS',
  ];

  for (const locale of ['en', 'zh'] as const) {
    const localeResults = results.filter((result) => result.locale === locale);
    if (localeResults.length === 0) continue;
    lines.push('', `### ${locale === 'en' ? 'English' : 'Chinese'}`);
    lines.push(JSON.stringify(localeResults, null, 2));
  }
  return lines.join('\n');
}

export function buildHealthReports(
  outputDir: string,
  scenarioOrder: string[],
): ScenarioResult[] {
  fs.mkdirSync(outputDir, { recursive: true });
  const allResults = readResultFragments(outputDir);
  const ordered = [
    ...sortResults(
      allResults.filter((result) => result.locale === 'en'),
      scenarioOrder,
    ),
    ...sortResults(
      allResults.filter((result) => result.locale === 'zh'),
      scenarioOrder,
    ),
  ];

  writeLocaleReport(
    outputDir,
    'en',
    ordered.filter((result) => result.locale === 'en'),
  );
  writeLocaleReport(
    outputDir,
    'zh',
    ordered.filter((result) => result.locale === 'zh'),
  );
  fs.writeFileSync(
    path.join(outputDir, 'health-check-review.txt'),
    buildReview(ordered),
  );
  return ordered;
}
