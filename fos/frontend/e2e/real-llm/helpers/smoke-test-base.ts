/**
 * Shared helpers for real-LLM smoke tests across all scenario categories.
 *
 * Provides: getActiveProviderIds, assertNoErrors, expectActionsVisible,
 *           buildAndRunScenario, assertLogContains
 */

import { Page, expect } from '@playwright/test';
import { ExperimentBuilder } from '../../helpers/experiment-builder';
import { SimulationWorkspace } from '../../helpers/simulation-workspace';
import { resolveAnyActiveProviderIds } from '../../helpers/providers';
import type { ScenarioConfig } from '../../fixtures/scenario-fixtures';

export interface ScenarioTestConfig {
  scenario: ScenarioConfig;
  locale?: string;
  agentNames?: string[];
  agentRolePrompts?: string[];
  zhAgentRolePrompts?: string[];
  params?: Record<string, string | number>;
  rounds?: number;
  advanceTimeoutMs?: number;
}

/**
 * Fetch active provider IDs, with retry for auto-discovery delay.
 *
 * The LM Studio auto-discovery runs asynchronously on login, so we
 * retry a few times with back-off to give it time to create the provider.
 *
 * Throws if no active providers are found after retries.
 */
export async function getActiveProviderIds(page: Page, agentCount: number): Promise<number[]> {
  let lastError: Error | null = null;

  for (let attempt = 0; attempt < 6; attempt++) {
    if (attempt > 0) {
      await page.waitForTimeout(2000 * attempt); // 2s, 4s, 6s, 8s, 10s
    }

    try {
      const ids = await resolveAnyActiveProviderIds(page, agentCount);
      if (ids && ids.length > 0) {
        return ids;
      }
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      // Continue retrying — provider might still be initializing
    }
  }

  throw lastError || new Error(
    'No active LLM provider found after 6 retries. ' +
    'Make sure Ollama or LM Studio is running and has at least one model loaded.',
  );
}

/**
 * Assert that the workspace has no error toasts.
 */
export async function assertNoErrors(workspace: SimulationWorkspace): Promise<void> {
  const errors = await workspace.collectErrorMessages();
  expect(errors, 'No error toasts should appear').toHaveLength(0);
}

/**
 * Verify that expected action buttons are visible in Step 3 of the wizard,
 * and that unexpected action buttons are NOT visible.
 */
export async function expectActionsVisible(
  page: Page,
  expectedActions: string[],
  unexpectedActions: string[],
): Promise<void> {
  for (const action of expectedActions) {
    await expect(
      page.getByText(new RegExp(`\\b${action}\\b`, 'i')).first(),
    ).toBeVisible({ timeout: 5_000 });
  }
  for (const action of unexpectedActions) {
    await expect(
      page.getByText(new RegExp(`\\b${action}\\b`, 'i')),
    ).not.toBeVisible();
  }
}

/**
 * Full-flow helper: build experiment (stops before Step 3 for action verification),
 * then select all actions, add agents, create, run rounds, and verify no errors.
 *
 * Caller MUST call expectActionsVisible() between configureDefaults() and
 * selectAllActions().
 *
 * Returns the SimulationWorkspace for additional per-scenario assertions.
 */
export async function buildAndRunScenario(
  page: Page,
  locale: string,
  config: ScenarioTestConfig,
): Promise<SimulationWorkspace> {
  const agentCount = config.agentNames?.length || config.scenario.agentNames.length;
  const providerIds = await getActiveProviderIds(page, agentCount);

  const builder = new ExperimentBuilder(page, locale);
  await builder.open();
  await builder.selectScenario(config.scenario.id);
  await builder.configureDefaults(config.params || config.scenario.parameters);

  // Caller must do expectActionsVisible() here, between configureDefaults and selectAllActions

  await builder.selectAllActions();

  const names = config.agentNames || config.scenario.agentNames;
  const enPrompts = config.agentRolePrompts || config.scenario.agentRolePrompts;
  const zhPrompts = config.zhAgentRolePrompts || config.scenario.zhAgentRolePrompts;
  await builder.addAgents(names, enPrompts, zhPrompts, providerIds);

  await builder.useDefaultNetwork();
  await builder.create();

  const workspace = new SimulationWorkspace(page, locale);
  await workspace.waitForReady();

  const rounds = config.rounds ?? config.scenario.rounds;
  const timeout = config.advanceTimeoutMs ?? config.scenario.advanceTimeoutMs;
  const advanceErrors = await workspace.advanceRounds(rounds, timeout);
  expect(advanceErrors, 'advanceRounds should not return errors').toHaveLength(0);

  await assertNoErrors(workspace);

  return workspace;
}

/**
 * Assert that the simulation body text matches at least one of the given patterns.
 */
export async function assertLogContains(page: Page, patterns: RegExp[]): Promise<void> {
  const body = (await page.textContent('body')) ?? '';
  const matched = patterns.some(p => p.test(body));
  expect(
    matched,
    `Expected log body to match at least one of: ${patterns.map(p => p.source).join(', ')}`,
  ).toBeTruthy();
}

/**
 * Extract the full body text from the simulation page for custom assertions.
 */
export async function getSimulationBodyText(page: Page): Promise<string> {
  return (await page.textContent('body')) ?? '';
}
