/**
 * Real-LLM smoke tests for Discussion scenarios.
 *
 * Tests:
 * - Open Discussion: pure conversation, verify meaningful content
 * - Council Chamber: 3 discuss + 1 vote + 1 post-vote (5 rounds), phase transitions
 *
 * Requires a configured, active local LLM provider (Ollama or LM Studio).
 */

import { test, expect } from '../fixtures';
import { SCENARIOS } from '../fixtures/scenario-fixtures';
import { ExperimentBuilder } from '../helpers/experiment-builder';
import { SimulationWorkspace } from '../helpers/simulation-workspace';
import {
  buildAndRunScenario,
  expectActionsVisible,
  assertNoErrors,
  assertLogContains,
  getActiveProviderIds,
  getSimulationBodyText,
} from './helpers/smoke-test-base';

// ---------------------------------------------------------------------------
// Open Discussion
// ---------------------------------------------------------------------------

test.describe('Open Discussion', () => {
  test('pure conversation: agents produce meaningful discussion content', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.open_discussion;

    // Custom params to give a concrete topic
    const params = {
      topic: 'Should universities require all students to learn programming regardless of their major?',
    };

    const workspace = await buildAndRunScenario(page, locale, {
      scenario,
      params,
      rounds: 3,
    });

    // Edge case: verify the body contains actual prose (not empty/placeholder responses)
    const body = await getSimulationBodyText(page);

    // Should have meaningful conversation content — at least some reasonable length
    expect(body.length).toBeGreaterThan(100);

    // Edge case: the topic should be reflected in the discussion
    const topicWords = ['programming', 'university', 'students', 'require'];
    const matchedTopics = topicWords.filter(w => new RegExp(w, 'i').test(body));
    expect(
      matchedTopics.length,
      `Expected discussion to reference the topic (matched: ${matchedTopics.join(', ')})`,
    ).toBeGreaterThan(0);

    console.log(
      `[open_discussion] body_length=${body.length} topic_matches=${matchedTopics.length}/${topicWords.length}`,
    );
  });
});

// ---------------------------------------------------------------------------
// Council Chamber (Voting Scenario)
// ---------------------------------------------------------------------------

test.describe('Council Chamber', () => {
  test('3 discuss rounds + transition to voting + post-vote discussion', async ({
    page,
    authedPage,
    locale,
  }) => {
    const scenario = SCENARIOS.council_chamber;
    const agentCount = scenario.agentNames.length;
    const providerIds = await getActiveProviderIds(page, agentCount);

    // Step 1: Build the experiment with a concrete proposal
    const builder = new ExperimentBuilder(page, locale);
    await builder.open();
    await builder.selectScenario(scenario.id);
    await builder.configureDefaults({
      proposal_text:
        'Proposal: Implement a four-day work week for all city employees on a six-month trial basis, with maintained salaries.',
    });

    // Step 2: Verify discussion + voting actions visible in Step 3
    await expectActionsVisible(page, ['Speak', 'Skip', 'Vote Yes', 'Vote No', 'Abstain'], []);

    await builder.selectAllActions();

    // Use shorter role prompts to speed up LLM response time
    await builder.addAgents(
      ['Councilor1', 'Councilor2', 'Councilor3', 'Councilor4', 'Councilor5'],
      [
        'You are Councilor1, leading the discussion. Propose concrete measures.',
        'You are Councilor2, focused on fairness for all groups.',
        'You are Councilor3, data-driven. Cite statistics.',
        'You are Councilor4, a consensus-builder.',
        'You are Councilor5, decisive and bold.',
      ],
      [
        '你是 Councilor1，主持讨论的议长。提出具体措施。',
        '你是 Councilor2，关注公平。主张各群体间的公平结果。',
        '你是 Councilor3，以数据为依据。引用统计和研究来支持观点。',
        '你是 Councilor4，共识搭建者。寻找共同点，弥合分歧。',
        '你是 Councilor5，果断大胆。提出雄心勃勃的计划。',
      ],
      providerIds,
    );

    await builder.useDefaultNetwork();
    await builder.create();

    // Step 3: Run 3 discussion rounds
    const workspace = new SimulationWorkspace(page, locale);
    await workspace.waitForReady();

    // Run 3 rounds of discussion
    const discussErrors = await workspace.advanceRounds(3);
    expect(discussErrors, 'Discussion rounds should not error').toHaveLength(0);
    await assertNoErrors(workspace);

    // Edge case: verify discussion content appeared
    const afterDiscuss = await getSimulationBodyText(page);
    expect(afterDiscuss.length, 'Discussion should produce content').toBeGreaterThan(50);

    // Step 4: Run voting round
    const voteErrors = await workspace.advanceRounds(1);
    expect(voteErrors, 'Voting round should not error').toHaveLength(0);
    await assertNoErrors(workspace);

    // Edge case: check that voting-related keywords appear
    const afterVote = await getSimulationBodyText(page);
    const hasVoteContent = /\bvote\b/i.test(afterVote);
    if (!hasVoteContent) {
      console.warn('[council_chamber] No vote-related content detected after voting round');
    }

    // Step 5: Run post-vote discussion round
    const postVoteErrors = await workspace.advanceRounds(1);
    expect(postVoteErrors, 'Post-vote discussion should not error').toHaveLength(0);
    await assertNoErrors(workspace);

    // Final edge case: verify full session ran without crashes
    const finalBody = await getSimulationBodyText(page);
    expect(finalBody.length, 'Full session should produce content').toBeGreaterThan(100);

    console.log(
      `[council_chamber] 5 rounds completed. body_length=${finalBody.length}`,
    );
  });
});
