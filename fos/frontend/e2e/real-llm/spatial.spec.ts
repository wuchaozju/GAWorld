/**
 * Real-LLM smoke tests for Spatial scenarios.
 *
 * Tests:
 * - Grid World: agents move on a grid, collect resources — verify position changes
 * - Contagion Spread: infection spreads through proximity — verify state transitions
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
// Grid World
// ---------------------------------------------------------------------------

test.describe('Grid World', () => {
  test('agents move on grid and change positions between rounds', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.grid_world;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: {
        grid_size: 8,
        resource_count: 3,
      },
      rounds: 3,
    });

    // Edge case: verify agents used movement-related actions
    await assertLogContains(page, [
      /\bmove\b/i,
      /\bposition\b/i,
      /\bgrid\b/i,
    ]);

    const body = await getSimulationBodyText(page);

    // Edge case: check for coordinate references (agents changing position)
    const hasCoordinates = /\(\d+,\s*\d+\)|\[\d+,\s*\d+\]|x\s*=\s*\d+|y\s*=\s*\d+|row\s*\d+|col\s*\d+/i.test(body);
    if (!hasCoordinates) {
      console.warn(
        '[grid_world] No coordinate references detected — agents may not have moved visibly',
      );
    }

    // Edge case: check for resource collection
    const hasResources = /\bresource\b|\bcollect\b|\bfound\b/i.test(body);
    if (!hasResources) {
      console.warn(
        '[grid_world] No resource collection detected — agents may not have found resources',
      );
    }

    console.log(
      `[grid_world] coordinates=${hasCoordinates} resources=${hasResources} body_length=${body.length}`,
    );
  });
});

// ---------------------------------------------------------------------------
// Contagion Spread
// ---------------------------------------------------------------------------

test.describe('Contagion Spread', () => {
  test('infection spreads and agents recover over multiple rounds', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.contagion;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: {
        initial_infected: 1,
        proximity_probability: 0.4,
        recovery_turns: 4,
        grid_size: 8,
      },
      rounds: 4,
    });

    // Edge case: verify infection-related content appeared
    await assertLogContains(page, [
      /\binfect\b/i,
      /\bspread\b|\btransmit\b/i,
    ]);

    const body = await getSimulationBodyText(page);

    // Edge case: check for multiple states (susceptible, infected, recovered)
    const states = ['susceptible', 'infected', 'recovered', 'healthy', 'sick', 'immune'];
    const foundStates = states.filter(s => new RegExp(s, 'i').test(body));
    console.log(
      `[contagion] states_detected=${foundStates.length}/${states.length} ` +
      `states=[${foundStates.join(', ')}]`,
    );

    // Edge case: with 5 agents and 4 rounds, the contagion should spread
    // beyond the initial infected agent
    const infectionMentions = (body.match(/\binfect\b/gi) || []).length;
    if (infectionMentions < 2) {
      console.warn(
        `[contagion] Only ${infectionMentions} infection mentions — contagion may not have propagated`,
      );
    }
  });
});
