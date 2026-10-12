/**
 * Global setup for E2E health-check tests.
 *
 * Cleans stale result files from previous runs, then verifies that
 * frontend and backend services are reachable before any test runs.
 * Fails fast with clear error messages if services are not running.
 *
 * Exports: default (global setup function)
 */

import { request as playwrightRequest } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Remove stale files from previous test runs so they don't
 * contaminate the current run's collected results.
 */
function cleanPreviousResults(): void {
  // Clean collected-results/ subdirectories (keep the dir itself)
  const outputDir = path.resolve(__dirname, 'collected-results');
  if (fs.existsSync(outputDir)) {
    const entries = fs.readdirSync(outputDir, { withFileTypes: true });
    for (const entry of entries) {
      const entryPath = path.join(outputDir, entry.name);
      if (entry.isDirectory()) {
        fs.rmSync(entryPath, { recursive: true, force: true });
      } else if (entry.name !== '.gitkeep') {
        fs.unlinkSync(entryPath);
      }
    }
  }

  // Clean backend test_results/ so stale debug logs don't get copied
  const testResultsDir = path.resolve(__dirname, '../../test_results');
  if (fs.existsSync(testResultsDir)) {
    const files = fs.readdirSync(testResultsDir).filter(f => f.endsWith('.txt'));
    for (const file of files) {
      fs.unlinkSync(path.join(testResultsDir, file));
    }
  }
}

async function globalSetup() {
  // Wipe stale results from any previous run
  cleanPreviousResults();

  const api = await playwrightRequest.newContext({
    baseURL: 'http://127.0.0.1:5173',
  });

  // Verify frontend is reachable
  const frontendResp = await api.get('/');
  if (!frontendResp.ok() && frontendResp.status() !== 200) {
    throw new Error(
      'Frontend not running on http://127.0.0.1:5173. Start with: cd frontend && npm run dev'
    );
  }

  // Verify backend API is reachable (scenarios endpoint)
  const backendResp = await api.get('/api/scenarios');
  if (!backendResp.ok()) {
    throw new Error(
      'Backend API not reachable. Start the backend server first.'
    );
  }

  await api.dispose();
}

export default globalSetup;
