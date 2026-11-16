/**
 * Real-LLM E2E tests using local Ollama.
 *
 * Validates core browser workflows with a real local Ollama model.
 * Requires a configured, active local Ollama provider. No fake, mock,
 * external-provider fallback, or silent skip is allowed.
 *
 * Scenarios covered:
 *   1. Custom Scenario v1  (speak + skip)
 *   2. Public Goods Game   (allocate / keep / reduce)
 *   3. Prisoner's Dilemma  (cooperate / defect)
 *
 * Exports: (Playwright test suite)
 */

import { Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { ExperimentBuilder } from './helpers/experiment-builder';
import { SimulationWorkspace } from './helpers/simulation-workspace';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Fetch active Ollama provider IDs from the API.
 *
 * Calls GET /api/providers inside the browser context (reuses auth session)
 * and filters for active Ollama providers. It verifies the selected provider.
 */
async function getOllamaProviderIds(page: Page, count: number): Promise<number[]> {
  const providers: Array<{ id: number; provider: string; is_active: boolean }> =
    await page.evaluate(async () => {
      const token = localStorage.getItem('fos.access');
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const resp = await fetch('/api/providers', { headers });
      if (!resp.ok) return [];
      return resp.json();
    });

  const ollamaIds = providers
    .filter(p => p.provider === 'ollama' && p.is_active)
    .map(p => p.id);

  if (ollamaIds.length === 0) {
    throw new Error(
      'No active Ollama provider found. Configure one in Settings > Providers.',
    );
  }

  const testResult = await page.evaluate(async (providerId) => {
    const token = localStorage.getItem('fos.access');
    const response = await fetch(`/api/providers/${providerId}/test`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    return {
      ok: response.ok,
      status: response.status,
      body: await response.text(),
    };
  }, ollamaIds[0]);
  if (!testResult.ok) {
    throw new Error(
      `Ollama provider preflight failed with HTTP ${testResult.status}: ${testResult.body}`,
    );
  }

  // Repeat if fewer providers than agents
  const ids: number[] = [];
  for (let i = 0; i < count; i++) {
    ids.push(ollamaIds[i % ollamaIds.length]);
  }
  return ids;
}

/** Assert that log/event content appeared after running a round. */
async function assertLogContent(page: Page) {
  const body = (await page.textContent('body')) ?? '';
  const hasContent =
    /round\s*\d/i.test(body) ||
    /speak|skip|allocate|keep|reduce|cooperate|defect/i.test(body) ||
    /Alice|Bob|Player/i.test(body);
  expect(hasContent, 'Expected log/event content after running a round').toBeTruthy();
}

// ---------------------------------------------------------------------------
// 1. Custom Scenario v1
// ---------------------------------------------------------------------------

test.describe('Custom Scenario v1', () => {
  test('select, configure, launch, run one round with local Ollama', async ({
    page,
    authedPage,
    locale,
  }) => {
    const providerIds = await getOllamaProviderIds(page, 2);

    // --- Build experiment ---
    const builder = new ExperimentBuilder(page, locale);
    await builder.open();
    await builder.selectScenario('custom');
    await builder.configureDefaults({
      custom_prompt:
        'Discuss whether the block should create a shared weekend cleanup plan. Keep responses under 20 words.',
    });

    // --- Step 3: verify action set is speak + skip only ---
    await expect(page.getByText(/\bSpeak\b/).first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/\bSkip\b/).first()).toBeVisible();

    // No game-theory actions should appear
    await expect(page.getByText(/\bCooperate\b/)).not.toBeVisible();
    await expect(page.getByText(/\bDefect\b/)).not.toBeVisible();
    await expect(page.getByText(/\bAllocate\b/)).not.toBeVisible();

    await builder.selectAllActions();
    await builder.addAgents(
      ['Alice', 'Bob'],
      [
        'You are Alice, a concise neighborhood organizer.',
        'You are Bob, a concise shop owner.',
      ],
      [
        '你是 Alice，一个简洁的社区组织者。',
        '你是 Bob，一个简洁的店主。',
      ],
      providerIds,
    );
    await builder.useDefaultNetwork();
    await builder.create();

    // --- Run simulation ---
    const workspace = new SimulationWorkspace(page, locale);
    await workspace.waitForReady();

    const advanceErrors = await workspace.advanceRounds(1);
    expect(advanceErrors, 'advanceRounds should not return errors').toHaveLength(0);

    // --- Verify results ---
    await assertLogContent(page);

    const errors = await workspace.collectErrorMessages();
    expect(errors, 'No error toasts should appear').toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 2. Public Goods Game
// ---------------------------------------------------------------------------

test.describe('Public Goods Game', () => {
  test('action set includes allocate/keep/reduce, excludes punish', async ({
    page,
    authedPage,
    locale,
  }) => {
    const providerIds = await getOllamaProviderIds(page, 3);

    const builder = new ExperimentBuilder(page, locale);
    await builder.open();
    await builder.selectScenario('public_goods');
    await builder.configureDefaults();

    // --- Step 3: verify canonical action set ---
    await expect(page.getByText(/\bAllocate\b/).first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/\bKeep\b/).first()).toBeVisible();
    await expect(page.getByText(/\bReduce\b/).first()).toBeVisible();

    // punish is NOT an active action
    await expect(page.getByText(/\bPunish\b/)).not.toBeVisible();

    await builder.selectAllActions();
    await builder.addAgents(
      ['Player1', 'Player2', 'Player3'],
      [
        'You are Player1, generous. Contribute 70-80% of your tokens.',
        'You are Player2, a free-rider. Contribute 0-2 tokens.',
        'You are Player3, conditional cooperator. Match last round average.',
      ],
      [
        '你是 Player1，慷慨。投入 70-80%。',
        '你是 Player2，搭便车。投入 0-2。',
        '你是 Player3，条件合作者。',
      ],
      providerIds,
    );
    await builder.useDefaultNetwork();
    await builder.create();

    const workspace = new SimulationWorkspace(page, locale);
    await workspace.waitForReady();

    const advanceErrors = await workspace.advanceRounds(1);
    expect(advanceErrors, 'advanceRounds should not return errors').toHaveLength(0);

    await assertLogContent(page);

    const errors = await workspace.collectErrorMessages();
    expect(errors, 'No error toasts should appear').toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 3. Prisoner's Dilemma
// ---------------------------------------------------------------------------

test.describe("Prisoner's Dilemma", () => {
  test('action set includes cooperate/defect', async ({
    page,
    authedPage,
    locale,
  }) => {
    const providerIds = await getOllamaProviderIds(page, 2);

    const builder = new ExperimentBuilder(page, locale);
    await builder.open();
    await builder.selectScenario('prisoners_dilemma');
    await builder.configureDefaults();

    // --- Step 3: verify cooperate / defect actions ---
    await expect(page.getByText(/\bCooperate\b/).first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/\bDefect\b/).first()).toBeVisible();

    await builder.selectAllActions();
    await builder.addAgents(
      ['Alice', 'Bob'],
      [
        'You are Alice, cooperative and values trust.',
        'You are Bob, pragmatic and considers outcomes carefully.',
      ],
      [
        '你是 Alice，重视信任、天性合作。',
        '你是 Bob，务实理性、权衡利弊。',
      ],
      providerIds,
    );
    await builder.useDefaultNetwork();
    await builder.create();

    const workspace = new SimulationWorkspace(page, locale);
    await workspace.waitForReady();

    const advanceErrors = await workspace.advanceRounds(1);
    expect(advanceErrors, 'advanceRounds should not return errors').toHaveLength(0);

    await assertLogContent(page);

    const errors = await workspace.collectErrorMessages();
    expect(errors, 'No error toasts should appear').toHaveLength(0);
  });
});
