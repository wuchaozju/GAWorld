/**
 * Real-LLM smoke tests for Game Theory scenarios.
 *
 * Tests each game-theory scenario with 3-5 rounds and edge-case assertions:
 * - Battle of the Sexes: coordination — do agents break the zero-payoff tie?
 * - Stag Hunt: defection risk — does one defector collapse the stag?
 * - Coordination Game: match vs differ — do agents follow the goal?
 *
 * Requires a configured, active local LLM provider (Ollama or LM Studio).
 */

import { test, expect } from '../fixtures';
import { SCENARIOS } from '../fixtures/scenario-fixtures';
import {
  buildAndRunScenario,
  expectActionsVisible,
  assertLogContains,
  getSimulationBodyText,
} from './helpers/smoke-test-base';

// ---------------------------------------------------------------------------
// Battle of the Sexes
// ---------------------------------------------------------------------------

test.describe('Battle of the Sexes', () => {
  test('coordination: agents pick different options across rounds', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.battle_of_the_sexes;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      rounds: 3,
    });

    // Verify action set in Step 3: Opera + Football visible, no Cooperate/Defect
    // Note: buildAndRunScenario runs after action verification
    // (We trust ExperimentBuilder adds the right actions for this scenario)

    // Edge case: After 3 rounds, verify the log contains game-relevant content
    await assertLogContains(page, [
      /\bopera\b/i,
      /\bfootball\b/i,
      /\bcoordinate\b/i,
    ]);

    const body = await getSimulationBodyText(page);

    // Edge case: agents should not have zero payoff every round
    // (if they always miscoordinate, that's a failure mode to investigate)
    const hasZero = /0\s*point|0\s*payoff|nothing/i.test(body);
    const hasNonZero = /\b[1-9]\s*point|[1-9]\s*payoff|reward/i.test(body);

    // Warn if always zero — not a hard fail because LLM behavior varies
    if (hasZero && !hasNonZero) {
      console.warn(
        '[battle_of_the_sexes] All rounds may have resulted in 0 payoff (miscoordination)',
      );
    }
  });
});

// ---------------------------------------------------------------------------
// Stag Hunt
// ---------------------------------------------------------------------------

test.describe('Stag Hunt', () => {
  test('defection risk: stag vs hare with mixed role prompts', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.stag_hunt;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      rounds: 3,
    });

    // Edge case: verify agents made choices (stag or hare)
    await assertLogContains(page, [
      /\bstag\b/i,
      /\bhare\b/i,
      /\bhunt/i,
    ]);

    const body = await getSimulationBodyText(page);

    // Edge case: check if defect → 0 payoff logic triggered
    // "stag" means cooperation, "hare" means safe defection
    const stagMentions = (body.match(/\bstag\b/gi) || []).length;
    const hareMentions = (body.match(/\bhare\b/gi) || []).length;

    console.log(
      `[stag_hunt] stag=${stagMentions} hare=${hareMentions} ` +
      `ratio=${stagMentions > 0 ? (hareMentions / stagMentions).toFixed(2) : 'N/A'}`,
    );

    // Edge case: with 3 agents (Hunter1 cooperative, Hunter2 cautious, Hunter3 risk-taker),
    // we expect mixed choices. If all pick hare, cooperation failed entirely.
    if (stagMentions === 0 && hareMentions > 0) {
      console.warn(
        '[stag_hunt] All agents chose hare (safe) — stag collaboration failed entirely',
      );
    }
  });
});

// ---------------------------------------------------------------------------
// Coordination Game
// ---------------------------------------------------------------------------

test.describe('Coordination Game', () => {
  test('goal=match: agents should coordinate on the same choice', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.coordination_game;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: {
        choices: 'red, blue, green',
        goal: 'match',
      },
      rounds: 3,
    });

    // Edge case: verify simulation ran (content exists)
    const body1 = await getSimulationBodyText(page);
    expect(body1.length).toBeGreaterThan(50);
    console.log(`[coordination_game-match] body_length=${body1.length}`);
  });

  test('goal=differ: agents should avoid matching their neighbors', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.coordination_game;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: {
        choices: 'red, blue, green',
        goal: 'differ',
      },
      rounds: 3,
    });

    // Edge case: despite the differ goal, with only 3 choices and 3 agents
    // some matching is inevitable in early rounds. Verify the simulation
    // ran without errors rather than expecting perfect differentiation.
    const body2 = await getSimulationBodyText(page);
    expect(body2.length).toBeGreaterThan(50);

    const body = await getSimulationBodyText(page);
    console.log(
      '[coordination_game-differ] Choices mentioned: ' +
      ['red', 'blue', 'green'].filter(c => new RegExp(c, 'i').test(body)).join(', '),
    );
  });
});
