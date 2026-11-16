/**
 * Dynamic LLM provider resolvers for E2E tests.
 *
 * Fetches providers from the API and returns randomized assignments
 * for N agents. Supports Ollama-specific and any-provider modes.
 *
 * Exports: resolveProviderIds, resolveOllamaProviderIds, resolveAnyActiveProviderIds
 */

import { Page } from '@playwright/test';

interface ProviderInfo {
  id: number;
  is_active: boolean;
  provider?: string;
}

/**
 * Fetch all providers from the API using the page's auth session.
 * Uses the Bearer token from localStorage (fos.access).
 */
async function fetchAllProviders(page: Page): Promise<ProviderInfo[]> {
  return page.evaluate(async () => {
    const token = localStorage.getItem('fos.access');
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const resp = await fetch('/api/providers', { headers });
    if (!resp.ok) return [];
    return resp.json();
  });
}

/**
 * Run a preflight test on a provider to verify it's reachable.
 * Throws if the test fails.
 */
async function preflightProvider(page: Page, providerId: number): Promise<void> {
  const testResult = await page.evaluate(async (pid: number) => {
    const token = localStorage.getItem('fos.access');
    const response = await fetch(`/api/providers/${pid}/test`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    return { ok: response.ok, status: response.status, body: await response.text() };
  }, providerId);

  if (!testResult.ok) {
    throw new Error(
      `Provider preflight failed with HTTP ${testResult.status}: ${testResult.body}`,
    );
  }
}

/**
 * Shuffle and assign provider IDs to N agents (repeats if fewer providers than agents).
 */
function assignProviderIds(ids: number[], agentCount: number): number[] {
  const result: number[] = [];
  for (let i = 0; i < agentCount; i++) {
    result.push(ids[Math.floor(Math.random() * ids.length)]);
  }
  return result;
}

/**
 * Fetch active providers from the API and return N random provider IDs.
 *
 * Intended for health-check style tests that need any available provider.
 * Does NOT run a preflight test (faster, used by the 14-scenario suite).
 *
 * @param page - Playwright page with auth session
 * @param agentCount - Number of agents to assign providers to
 * @returns Array of provider IDs, or undefined if no providers found
 */
export async function resolveProviderIds(
  page: Page,
  agentCount: number,
): Promise<number[] | undefined> {
  const providers = await fetchAllProviders(page);
  const active = providers.filter(p => p.is_active).map(p => p.id);
  if (active.length === 0) return undefined;
  return assignProviderIds(active, agentCount);
}

/**
 * Resolve N provider IDs, filtering specifically for active Ollama providers.
 * Runs a preflight test on the first provider to verify it's reachable.
 *
 * @param page - Playwright page with auth session
 * @param agentCount - Number of agents to assign providers to
 * @returns Array of provider IDs, or undefined if no Ollama providers found
 */
export async function resolveOllamaProviderIds(
  page: Page,
  agentCount: number,
): Promise<number[] | undefined> {
  const providers = await fetchAllProviders(page);
  const ollamaIds = providers
    .filter(p => p.provider === 'ollama' && p.is_active)
    .map(p => p.id);

  if (ollamaIds.length === 0) return undefined;

  await preflightProvider(page, ollamaIds[0]);
  return assignProviderIds(ollamaIds, agentCount);
}

/**
 * Resolve N provider IDs from ANY active provider (Ollama, LM Studio, OpenAI, etc.).
 * Runs a preflight test on the first provider to verify it's reachable.
 *
 * @param page - Playwright page with auth session
 * @param agentCount - Number of agents to assign providers to
 * @returns Array of provider IDs, or undefined if no active providers found
 */
export async function resolveAnyActiveProviderIds(
  page: Page,
  agentCount: number,
): Promise<number[] | undefined> {
  const providers = await fetchAllProviders(page);
  const active = providers.filter(p => p.is_active).map(p => p.id);

  if (active.length === 0) return undefined;

  await preflightProvider(page, active[0]);
  return assignProviderIds(active, agentCount);
}
