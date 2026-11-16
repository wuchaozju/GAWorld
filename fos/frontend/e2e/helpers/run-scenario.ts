/**
 * Scenario runner helper for E2E health-check tests.
 *
 * Orchestrates the full flow for a single scenario: create simulation,
 * run rounds, collect errors, and gather test_results/ files.
 * Never throws — all errors are caught and recorded.
 *
 * Exports: runScenario, ScenarioResult
 */

import type { ConsoleMessage, Page, Request, Response } from '@playwright/test';
import { ExperimentBuilder } from './experiment-builder';
import { SimulationWorkspace } from './simulation-workspace';
import { ResultCollector } from './result-collector';
import { resolveProviderIds } from './providers';
import { ScenarioConfig, getScenarioForLocale } from '../fixtures/scenario-fixtures';

export interface ScenarioResult {
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

export function formatBackendResponseFailure(
  status: number,
  method: string,
  rawUrl: string,
): string {
  let displayUrl = rawUrl;
  try {
    const parsed = new URL(rawUrl);
    displayUrl = `${parsed.pathname}${parsed.search}`;
  } catch {
    displayUrl = rawUrl;
  }
  return `HTTP ${status} ${method} ${displayUrl}`;
}

export function formatBackendRequestFailure(
  method: string,
  rawUrl: string,
  failureText: string,
): string | null {
  const normalizedFailure = failureText.toUpperCase();
  if (
    normalizedFailure.includes('ERR_ABORTED')
    || normalizedFailure.includes('BINDING_ABORTED')
    || normalizedFailure.includes('REQUEST_ABORTED')
  ) {
    return null;
  }

  let displayUrl = rawUrl;
  try {
    const parsed = new URL(rawUrl);
    displayUrl = `${parsed.pathname}${parsed.search}`;
  } catch {
    displayUrl = rawUrl;
  }
  return `${method} ${displayUrl}: ${failureText}`;
}

export function determineScenarioStatus(
  result: Pick<ScenarioResult, 'status' | 'uiErrors' | 'warnings' | 'backendErrors'>,
): ScenarioResult['status'] {
  if (result.status === 'crashed' || result.status === 'timeout') {
    return result.status;
  }
  if (
    result.uiErrors.length > 0
    || result.warnings.length > 0
    || result.backendErrors.length > 0
  ) {
    return 'ui_errors';
  }
  return 'passed';
}

function isBackendApiUrl(rawUrl: string): boolean {
  try {
    const parsed = new URL(rawUrl);
    return parsed.pathname.startsWith('/api/');
  } catch {
    return rawUrl.includes('/api/');
  }
}

export async function runScenario(
  page: Page,
  scenario: ScenarioConfig,
  locale: string,
): Promise<ScenarioResult> {
  const result: ScenarioResult = {
    id: scenario.id,
    name: scenario.name,
    locale: locale as 'en' | 'zh',
    status: 'unknown',
    uiErrors: [],
    warnings: [],
    backendErrors: [],
    testResultFiles: [],
    durationMs: 0,
  };

  const collector = new ResultCollector(scenario.id);
  const start = Date.now();
  const seenBackendErrors = new Set<string>();

  const recordBackendError = (message: string): void => {
    if (seenBackendErrors.has(message)) return;
    seenBackendErrors.add(message);
    result.backendErrors.push(message);
  };

  const responseHandler = (response: Response): void => {
    const rawUrl = response.url();
    if (!isBackendApiUrl(rawUrl) || response.status() < 500) return;
    recordBackendError(
      formatBackendResponseFailure(
        response.status(),
        response.request().method(),
        rawUrl,
      ),
    );
  };

  const requestFailedHandler = (request: Request): void => {
    const rawUrl = request.url();
    if (!isBackendApiUrl(rawUrl)) return;
    const failureText = request.failure()?.errorText || 'request failed';
    const failure = formatBackendRequestFailure(
      request.method(),
      rawUrl,
      failureText,
    );
    if (failure) recordBackendError(failure);
  };

  const consoleHandler = (message: ConsoleMessage): void => {
    if (message.type() !== 'error') return;
    const text = message.text();
    if (!text.includes('[getTreeGraph] Failed to fetch tree graph')) return;
    recordBackendError(text);
  };

  page.on('response', responseHandler);
  page.on('requestfailed', requestFailedHandler);
  page.on('console', consoleHandler);

  try {
    const builder = new ExperimentBuilder(page, locale);

    // Adjust agent count for locale (ZH uses fewer agents to reduce Ollama load)
    const localeScenario = getScenarioForLocale(scenario, locale);

    // Resolve providers dynamically from the API (portable across systems)
    const providerIds = await resolveProviderIds(page, localeScenario.agentNames.length);

    await builder.createSimulationWithDefaults(
      localeScenario.id,
      localeScenario.agentNames,
      localeScenario.agentRolePrompts,
      localeScenario.zhAgentRolePrompts,
      localeScenario.parameters,
      providerIds,
    );

    const workspace = new SimulationWorkspace(page, locale);
    await workspace.waitForReady();

    // Collect any UI error toasts before advancing
    result.uiErrors.push(...await workspace.collectErrorMessages());

    // Run the simulation rounds
    const advanceErrors = await workspace.advanceRounds(scenario.rounds, scenario.advanceTimeoutMs);
    result.warnings.push(...advanceErrors);

    // Collect errors again after running
    result.uiErrors.push(...await workspace.collectErrorMessages());

    result.status = determineScenarioStatus(result);
  } catch (err) {
    result.status = 'crashed';
    result.uiErrors.push(String(err));
    result.status = determineScenarioStatus(result);
  } finally {
    page.off('response', responseHandler);
    page.off('requestfailed', requestFailedHandler);
    page.off('console', consoleHandler);
  }

  // Always try to collect test_results/ files
  try {
    result.testResultFiles = collector.collect();
  } catch (collectErr) {
    result.warnings.push(`Failed to collect test_results: ${String(collectErr)}`);
  }

  result.status = determineScenarioStatus(result);
  result.durationMs = Date.now() - start;
  return result;
}
