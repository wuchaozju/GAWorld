/**
 * Playwright configuration for E2E health-check runner.
 *
 * Runs all 13 scenarios in two languages (English, Chinese) sequentially
 * with long timeouts for LLM calls. No retries — we want to see failures
 * as-is for diagnostics.
 *
 * Automatically starts both backend (uvicorn) and frontend (vite) servers
 * before tests and tears them down after. reuseExistingServer: true means
 * manually started servers are reused without double-starting.
 *
 * Exports: default (Playwright config)
 */

import { defineConfig } from '@playwright/test';
import { existsSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';
import os from 'os';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const repoRoot = resolve(__dirname, '..');
const virtualenvPython = process.platform === 'win32'
  ? resolve(repoRoot, '.venv', 'Scripts', 'python.exe')
  : resolve(repoRoot, '.venv', 'bin', 'python');
const backendPython = process.env.FOS_PLAYWRIGHT_PYTHON
  || process.env.PYTHON
  || (existsSync(virtualenvPython) ? virtualenvPython : 'python');
const playwrightOutputDir = resolve(os.tmpdir(), 'fos-playwright-results');
const playwrightReportPath = resolve(os.tmpdir(), 'fos-playwright-report.json');
const pythonPath = resolve(repoRoot, 'src');
const backendCommand = process.platform === 'win32'
  ? `set PYTHONPATH=${pythonPath}&& "${backendPython}" -m uvicorn fos.backend.main:app --host 127.0.0.1 --port 8000`
  : `PYTHONPATH="${pythonPath}" "${backendPython}" -m uvicorn fos.backend.main:app --host 127.0.0.1 --port 8000`;
const chromeExecutable = process.platform === 'win32'
  ? resolve(process.env.LOCALAPPDATA || '', 'Google', 'Chrome', 'Application', 'chrome.exe')
  : '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const browserChannel = existsSync(chromeExecutable) ? 'chrome' : undefined;

export default defineConfig({
  globalSetup: resolve(__dirname, 'e2e/global-setup.ts'),
  testDir: './e2e',
  fullyParallel: false,        // Sequential — LLM backend can't handle parallel
  workers: 1,
  retries: 0,                  // No retries — see failures as-is
  timeout: 300_000,            // 5 min per scenario (LLM × N agents × 3 rounds)
  expect: {
    timeout: 30_000,
  },
  outputDir: playwrightOutputDir,
  reporter: [
    ['list'],
    ['json', { outputFile: playwrightReportPath }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'on-first-retry',
    video: 'off',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: backendCommand,
      cwd: repoRoot,
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: 'npm run dev',
      cwd: resolve(__dirname),
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: true,
      timeout: 30_000,
    },
  ],
  projects: [
    {
      name: 'en',
      use: {
        browserName: 'chromium',
        channel: browserChannel,
        locale: 'en',
      },
    },
    {
      name: 'zh',
      testIgnore: /real-llm\.spec\.ts/,
      use: {
        browserName: 'chromium',
        channel: browserChannel,
        locale: 'zh',
      },
    },
  ],
});
