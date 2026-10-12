/**
 * Debug test: run one sociology scenario and dump body text.
 */
import { test, expect } from '../fixtures';
import { SCENARIOS } from '../fixtures/scenario-fixtures';
import { ExperimentBuilder } from '../helpers/experiment-builder';
import { SimulationWorkspace } from '../helpers/simulation-workspace';
import { resolveAnyActiveProviderIds } from '../helpers/providers';

test('debug body text', async ({ page, authedPage, locale }) => {
  const scenario = SCENARIOS.resource_scarcity;
  const providerIds = await resolveAnyActiveProviderIds(page, 2);
  if (!providerIds) throw new Error('No provider');

  const builder = new ExperimentBuilder(page, locale);
  await builder.open();
  await builder.selectScenario(scenario.id);
  await builder.configureDefaults({ resource_amount: 50, initial_distribution: 'equal' });
  await builder.selectAllActions();
  await builder.addAgents(
    ['Alice', 'Bob'],
    ['You are Alice, generous.', 'You are Bob, selfish.'],
    ['你是 Alice', '你是 Bob'],
    providerIds,
  );
  await builder.useDefaultNetwork();
  await builder.create();

  const workspace = new SimulationWorkspace(page, locale);
  await workspace.waitForReady();
  const errors = await workspace.advanceRounds(2);
  expect(errors).toHaveLength(0);

  const body = (await page.textContent('body')) ?? '';
  console.log('=== BODY TEXT START ===');
  console.log(body);
  console.log('=== BODY TEXT END ===');
  console.log(`Body length: ${body.length}`);
});
