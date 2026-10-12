/**
 * Post-run aggregation script for E2E health-check results.
 *
 * Reads run-report-en.json and run-report-zh.json, plus collected
 * LLM debug logs, then prints a bilingual summary.
 *
 * Usage: npx ts-node e2e/scripts/collect-and-report.ts
 *
 * Exports: none (CLI script)
 */

import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

interface ScenarioResult {
  id: string;
  name: string;
  locale: 'en' | 'zh';
  status: 'passed' | 'ui_errors' | 'crashed' | 'timeout' | 'unknown';
  uiErrors: string[];
  warnings: string[];
  backendErrors: string[];
  testResultFiles: string[];
  durationMs: number;
}

const RESULTS_DIR = path.resolve(__dirname, '../collected-results');

function printReport(locale: string, results: ScenarioResult[]) {
  console.log(`\n${'='.repeat(60)}`);
  console.log(`  E2E Health-Check Report (${locale.toUpperCase()})`);
  console.log('='.repeat(60));

  for (const r of results) {
    const icon = r.status === 'passed' ? 'OK' : r.status === 'ui_errors' ? 'WARN' : 'FAIL';
    const duration = (r.durationMs / 1000).toFixed(1);
    const logCount = r.testResultFiles.length;

    console.log(`\n[${icon}] ${r.name}`);
    console.log(`  Status: ${r.status}  |  Duration: ${duration}s  |  Log files: ${logCount}`);

    if (r.uiErrors.length > 0) {
      console.log('  UI Errors:');
      for (const err of r.uiErrors) {
        console.log(`    - ${err}`);
      }
    }

    const backendErrors = r.backendErrors || [];
    if (backendErrors.length > 0) {
      console.log('  Backend Errors:');
      for (const err of backendErrors) {
        console.log(`    - ${err}`);
      }
    }

    if (r.warnings.length > 0) {
      console.log('  Warnings:');
      for (const w of r.warnings) {
        console.log(`    - ${w}`);
      }
    }

    if (logCount > 0) {
      console.log('  Log files:');
      for (const f of r.testResultFiles) {
        console.log(`    - ${path.relative(RESULTS_DIR, f)}`);
      }
    }
  }

  const passed = results.filter(r => r.status === 'passed').length;
  const total = results.length;
  const broken = results.filter(r => r.status === 'crashed' || r.status === 'timeout').length;

  console.log(`\n${'-'.repeat(60)}`);
  console.log(`Total (${locale}): ${passed}/${total} passed, ${broken} broken`);
}

function compareLocales(enResults: ScenarioResult[], zhResults: ScenarioResult[]) {
  console.log(`\n${'='.repeat(60)}`);
  console.log('  Cross-Language Comparison');
  console.log('='.repeat(60));

  for (const en of enResults) {
    const zh = zhResults.find(r => r.id === en.id);
    if (!zh) continue;

    const match = en.status === zh.status;
    const icon = match ? '=' : '!=';
    console.log(`  [${icon}] ${en.name}: EN=${en.status} | ZH=${zh.status}`);
  }
}

function main() {
  const enPath = path.join(RESULTS_DIR, 'run-report-en.json');
  const zhPath = path.join(RESULTS_DIR, 'run-report-zh.json');

  let enResults: ScenarioResult[] = [];
  let zhResults: ScenarioResult[] = [];

  if (fs.existsSync(enPath)) {
    enResults = JSON.parse(fs.readFileSync(enPath, 'utf-8'));
    printReport('en', enResults);
  } else {
    console.log('No English report found. Run the en project first.');
  }

  if (fs.existsSync(zhPath)) {
    zhResults = JSON.parse(fs.readFileSync(zhPath, 'utf-8'));
    printReport('zh', zhResults);
  } else {
    console.log('No Chinese report found. Run the zh project first.');
  }

  if (enResults.length > 0 && zhResults.length > 0) {
    compareLocales(enResults, zhResults);
  }

  console.log('\nNext step: Give the collected results to Claude Code with the diagnostic prompt.');
  console.log(`  Reports: ${RESULTS_DIR}/run-report-{en,zh}.json`);
  console.log(`  Logs:    ${RESULTS_DIR}/`);
}

main();
