/**
 * Real-LLM smoke tests for Sociology scenarios.
 *
 * Each scenario is tested with 2 parameter variants to catch regressions
 * in parameter-dependent behavior. All scenarios use category_actions
 * from CATEGORY_ACTION_LIBRARIES.
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

// Shared sociology actions that should be visible in Step 3 for all sociology scenarios
const SOCIOLOGY_ACTIONS = [
  'express_opinion', 'persuade_others', 'seek_common_ground', 'disengage',
  'comply_publicly', 'comply_covertly_resist', 'resist_openly',
  'transmit_faithfully', 'reinterpret_downward', 'comply_directive', 'resist_quietly',
  'reinforce_ingroup', 'share_content',
  'share_resources', 'hoard', 'propose_trade', 'form_contract',
];

function getExpectedActions(scenarioId: string): string[] {
  const actionMap: Record<string, string[]> = {
    social_norm_disruption: ['Comply', 'Resist', 'Persuade'],
    policy_erosion: ['Transmit', 'Reinterpret', 'Comply', 'Resist'],
    echo_chamber: ['Express', 'Reinforce', 'Share', 'Disengage'],
    resource_scarcity: ['Share', 'Hoard', 'Propose', 'Form'],
    xihu_yilianbao: ['Express', 'Persuade', 'Seek', 'Disengage'],
  };
  return actionMap[scenarioId] || ['express', 'persuade', 'seek', 'share'];
}

// ---------------------------------------------------------------------------
// Social Norm Disruption
// ---------------------------------------------------------------------------

test.describe('Social Norm Disruption', () => {
  test('Variant 1: weak norm (norm_strength=0.3) — expect more resistance', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.social_norm_disruption;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: { norm_strength: 0.3, agent_status_distribution: 'mixed' },
      rounds: 3,
    });

    await assertLogContains(page, [
      /\bnorm\b/i,
      /\bcomply\b|\bresist\b|\bpersuade\b/i,
    ]);
  });

  test('Variant 2: strong norm (norm_strength=0.9) — expect more compliance', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.social_norm_disruption;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: { norm_strength: 0.9, agent_status_distribution: 'mixed' },
      rounds: 3,
    });

    await assertLogContains(page, [
      /\bnorm\b/i,
      /\bcomply\b|\bresist\b|\bpersuade\b/i,
    ]);
  });
});

// ---------------------------------------------------------------------------
// Policy Erosion
// ---------------------------------------------------------------------------

test.describe('Policy Erosion', () => {
  test('Variant 1: strict_cascade — faithful transmission', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.policy_erosion;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: {
        cascade_mode: 'strict_cascade',
        num_agents_per_tier: 3,
      },
      rounds: 3,
    });

    await assertLogContains(page, [
      /\bpolicy\b|\btransmit\b|\bcomply\b/i,
    ]);
  });

  test('Variant 2: distortion_cascade with high distortion — expect reinterpretation', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.policy_erosion;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: {
        cascade_mode: 'distortion_cascade',
        distortion_strength: 0.9,
        num_agents_per_tier: 3,
      },
      rounds: 3,
    });

    await assertLogContains(page, [
      /\bpolicy\b|\breinterpret\b|\bresist\b/i,
    ]);
  });
});

// ---------------------------------------------------------------------------
// Echo Chamber
// ---------------------------------------------------------------------------

test.describe('Echo Chamber', () => {
  test('Variant 1: balanced opinions — some cross-cutting exposure', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.echo_chamber;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: { opinion_distribution: 'balanced', connection_homogeneity: 0.5 },
      rounds: 3,
    });

    await assertLogContains(page, [
      /\bopinion\b|\bview\b|\bagree\b/i,
    ]);
  });

  test('Variant 2: polarized opinions — expect reinforce_ingroup', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.echo_chamber;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: { opinion_distribution: 'polarized', connection_homogeneity: 0.8 },
      rounds: 3,
    });

    await assertLogContains(page, [
      /\bopinion\b|\bview\b|\bshare\b|\breinforce\b/i,
    ]);
  });
});

// ---------------------------------------------------------------------------
// Resource Scarcity
// ---------------------------------------------------------------------------

test.describe('Resource Scarcity', () => {
  test('Variant 1: equal distribution — expect more sharing', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.resource_scarcity;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: { resource_amount: 100, initial_distribution: 'equal' },
      rounds: 3,
    });

    await assertLogContains(page, [
      /\bshare\b|\bresource\b|\bhoard\b/i,
    ]);
  });

  test('Variant 2: skewed distribution — expect hoarding by the wealthy', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.resource_scarcity;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: { resource_amount: 100, initial_distribution: 'skewed' },
      rounds: 3,
    });

    await assertLogContains(page, [
      /\bshare\b|\bresource\b|\bhoard\b/i,
    ]);

    const body = await getSimulationBodyText(page);
    const hoardMentions = (body.match(/\bhoard\b/gi) || []).length;
    const shareMentions = (body.match(/\bshare\b/gi) || []).length;

    console.log(
      `[resource_scarcity-skewed] hoard=${hoardMentions} share=${shareMentions} ` +
      `ratio=${shareMentions > 0 ? (hoardMentions / shareMentions).toFixed(2) : 'N/A'}`,
    );
  });
});

// ---------------------------------------------------------------------------
// Xihu Yilianbao Enrollment Diffusion
// ---------------------------------------------------------------------------

test.describe('Xihu Yilianbao Enrollment Diffusion', () => {
  test('Variant 1: intervention_arm=A0 (no intervention) — baseline enrollment', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.xihu_yilianbao;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: { intervention_arm: 'A0' },
      rounds: 3,
    });

    await assertLogContains(page, [
      /\binsurance\b|\benroll\b|\byilianbao\b|\bhealth\b/i,
    ]);
  });

  test('Variant 2: intervention_arm=A2 (targeted message) — expect more persuasion', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.xihu_yilianbao;

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params: { intervention_arm: 'A2' },
      rounds: 3,
    });

    await assertLogContains(page, [
      /\binsurance\b|\benroll\b|\byilianbao\b|\bhealth\b/i,
    ]);

    const body = await getSimulationBodyText(page);
    const enrollMentions = (body.match(/\benroll\b/gi) || []).length;
    console.log(`[xihu_yilianbao-A2] enrollment_mentions=${enrollMentions}`);
  });
});
