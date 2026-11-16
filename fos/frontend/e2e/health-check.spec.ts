/**
 * This file runs every simulation health check and saves durable reports.
 *
 * Each scenario runs through the builder and simulation workspace.
 * saveResult writes one atomic fragment before assertions can stop a worker.
 * afterAll rebuilds complete English, Chinese, and readable reports.
 */

import { test, expect } from './fixtures';
import { getAllScenarios, SCENARIOS } from './fixtures/scenario-fixtures';
import { runScenario } from './helpers/run-scenario';
import {
  buildHealthReports,
  writeResultFragment,
} from './helpers/health-report-store';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const allScenarios = getAllScenarios();
const outputDir = path.resolve(__dirname, 'collected-results');
const scenarioOrder = [...allScenarios.map((scenario) => scenario.id), 'custom'];

function saveResult(
  result: Awaited<ReturnType<typeof runScenario>>,
  resultKey: string,
): void {
  writeResultFragment(outputDir, result, resultKey);
  buildHealthReports(outputDir, scenarioOrder);
}

function expectSuccessfulResult(
  result: Awaited<ReturnType<typeof runScenario>>,
): void {
  expect(result.uiErrors).toEqual([]);
  expect(result.backendErrors).toEqual([]);
  expect(result.warnings).toEqual([]);
  expect(result.status).toBe('passed');
}

for (const scenario of allScenarios) {
  test(`health-check (${scenario.name})`, async ({ page, authedPage, locale }) => {
    const result = await runScenario(page, scenario, locale);
    saveResult(result, `${scenario.id}-health`);

    console.log(
      `[${locale}] [${scenario.id}] status=${result.status} `
      + `ui_errors=${result.uiErrors.length} `
      + `backend_errors=${result.backendErrors.length} `
      + `warnings=${result.warnings.length} `
      + `duration=${result.durationMs}ms`,
    );
    expectSuccessfulResult(result);
  });
}

test('custom scenario - prompt-based simulation', async ({
  page,
  authedPage,
  locale,
}) => {
  const result = await runScenario(page, SCENARIOS.custom, locale);
  saveResult(result, 'custom-prompt');
  expectSuccessfulResult(result);
});

test.afterAll(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  const results = buildHealthReports(outputDir, scenarioOrder);
  const passed = results.filter((result) => result.status === 'passed').length;
  console.log(`\nHealth check report: ${passed}/${results.length} passed`);
});
