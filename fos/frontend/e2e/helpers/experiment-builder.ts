/**
 * Page object for the 6-step Experiment Builder wizard.
 *
 * Navigates through each step using locale-aware selectors from
 * the i18n system. All button text is looked up via t() helper.
 *
 * Supports: parameter overrides (Step 2), locale-aware role prompts,
 * and per-agent LLM provider selection (Step 4).
 *
 * Exports: ExperimentBuilder
 */

import { Page } from '@playwright/test';
import { t } from './locale-helper';

/** Maps scenario IDs to their UI category */
const SCENARIO_CATEGORY: Record<string, string> = {
  custom: 'custom',
  gaworld: 'generative_city',
  prisoners_dilemma: 'game_theory',
  battle_of_the_sexes: 'game_theory',
  stag_hunt: 'game_theory',
  public_goods: 'game_theory',
  coordination_game: 'game_theory',
  open_discussion: 'discussion',
  council_chamber: 'discussion',
  grid_world: 'spatial',
  contagion: 'spatial',
  social_norm_disruption: 'sociology',
  policy_erosion: 'sociology',
  echo_chamber: 'sociology',
  resource_scarcity: 'sociology',
  xihu_yilianbao: 'sociology',
};

export class ExperimentBuilder {
  readonly page: Page;
  readonly locale: string;

  constructor(page: Page, locale: string) {
    this.page = page;
    this.locale = locale;
  }

  /** Open the preset experiment builder directly. */
  async open() {
    await this.page.goto('/simulations/create/preset');
    await this.page.waitForLoadState('networkidle');

    // Wait for the "Next" button — it's always visible on the builder page
    const nextText = t('experimentBuilder.next', this.locale);
    await this.page.getByRole('button', { name: new RegExp(nextText, 'i') }).waitFor({
      state: 'visible',
      timeout: 15_000,
    });
  }

  /** Step 1: Select a scenario by clicking its category then its card */
  async selectScenario(scenarioId: string) {
    const category = SCENARIO_CATEGORY[scenarioId];

    // Expand the category accordion
    if (category) {
      const categoryText = t(`scenario.category.${category}`, this.locale);
      const categoryBtn = this.page.getByRole('button', {
        name: new RegExp(categoryText, 'i'),
      }).first();
      if (await categoryBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
        await categoryBtn.click();
        await this.page.waitForTimeout(500);
      }
    }

    // Click the scenario card — look up the name from i18n
    const scenarioNameKey = `scenario.${category}.${scenarioId}.name`;
    const scenarioName = t(scenarioNameKey, this.locale);

    const scenarioCard = this.page.locator('button').filter({
      hasText: new RegExp(scenarioName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'),
    }).first();
    await scenarioCard.click();
    await this.page.waitForTimeout(500);

    await this.clickNext();
  }

  /** Step 2: Configure parameters then proceed */
  async configureDefaults(params?: Record<string, string | number>) {
    if (params && Object.keys(params).length > 0) {
      await this.fillParameters(params);
    }
    await this.clickNext();
  }

  /**
   * Fill in parameter fields by looking up their labels via i18n.
   * Falls back to known English labels when i18n key is missing.
   */
  private async fillParameters(params: Record<string, string | number>) {
    await this.page.waitForTimeout(500);

    // Fallback labels for params without i18n entries
    const fallbackLabels: Record<string, Record<string, string>> = {
      en: {
        proposal_text: 'Proposal Text',
        topic: 'Discussion Topic',
        custom_prompt: 'Custom Scenario Prompt',
      },
      zh: {
        proposal_text: '提案文本',
        topic: '讨论主题',
        custom_prompt: '自定义场景提示',
      },
    };

    for (const [key, value] of Object.entries(params)) {
      // Parameter labels are rendered by Step2StarterTemplate using
      // t('experimentBuilder.paramLabels.${param.key}', { defaultValue: param.label })
      const i18nKey = `experimentBuilder.paramLabels.${key}`;
      let paramLabel = t(i18nKey, this.locale);

      // If t() returned the raw key, use fallback
      if (paramLabel === i18nKey) {
        paramLabel = fallbackLabels[this.locale]?.[key]
          || fallbackLabels.en[key]
          || key;
      }

      const escapedLabel = paramLabel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

      // Find the label element, then the nearest textarea or input sibling
      const label = this.page.locator('label').filter({
        hasText: new RegExp(escapedLabel, 'i'),
      }).first();

      if (await label.isVisible({ timeout: 3_000 }).catch(() => false)) {
        // Find the input/textarea within the same parent container
        const container = label.locator('..');
        const textarea = container.locator('textarea').first();
        const input = container.locator('input[type="text"]').first();

        if (await textarea.isVisible({ timeout: 1_000 }).catch(() => false)) {
          await textarea.clear();
          await textarea.fill(String(value));
        } else if (await input.isVisible({ timeout: 1_000 }).catch(() => false)) {
          await input.clear();
          await input.fill(String(value));
        }
      }
    }
    await this.page.waitForTimeout(500);
  }

  /** Step 3: Select all available actions (default behavior) */
  async selectAllActions() {
    await this.page.waitForTimeout(1000);
    await this.clickNext();
  }

  /** Step 4: Add agents by name with locale-aware role prompts */
  async addAgents(
    names: string[],
    enRolePrompts: string[],
    zhRolePrompts: string[],
    providerIds?: number[],
  ) {
    await this.page.waitForTimeout(1000);

    const addText = t('experimentBuilder.step4.addAgentType', this.locale);
    const escaped = addText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

    for (let i = 0; i < names.length; i++) {
      // Pick role prompt based on locale
      const rolePrompt = this.locale === 'zh' ? zhRolePrompts[i] : enRolePrompts[i];

      // Find inputs by their i18n placeholder text
      const labelPlaceholder = t('experimentBuilder.step4.typeLabelPlaceholder', this.locale);
      const labelInput = this.page.getByPlaceholder(labelPlaceholder).first();

      await labelInput.waitFor({ state: 'visible', timeout: 3_000 });
      await labelInput.clear();
      await labelInput.fill(names[i]);

      const rolePlaceholder = t('experimentBuilder.step4.rolePromptPlaceholder', this.locale);
      const roleInput = this.page.getByPlaceholder(rolePlaceholder).first();

      if (await roleInput.isVisible({ timeout: 1_000 }).catch(() => false)) {
        await roleInput.clear();
        await roleInput.fill(rolePrompt);
      }

      // Click "Add Agent Type" for every agent (including last)
      // to add them to the list before proceeding
      const addBtn = this.page.getByRole('button', { name: new RegExp(escaped, 'i') });
      await addBtn.waitFor({ state: 'visible', timeout: 3_000 });
      // Wait for button to become enabled after filling the label
      await this.page.waitForTimeout(500);
      await addBtn.click();
      await this.page.waitForTimeout(500);

      // Set per-agent LLM provider if specified
      if (providerIds && providerIds[i] != null) {
        await this.setAgentProvider(names[i], providerIds[i]);
      }
    }

    await this.clickNext();
  }

  /**
   * Expand an agent in the list and set its LLM provider.
   *
   * The agent list uses compact rows that expand on click.
   * The expanded form has an LLM Provider dropdown.
   */
  private async setAgentProvider(agentName: string, providerId: number) {
    const llmLabel = t('experimentBuilder.step4.llmProvider', this.locale);

    // Find the agent's compact row in the list and click to expand
    const agentRow = this.page.locator('div').filter({
      hasText: new RegExp(`^\\s*${agentName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`),
    }).first();

    // The agent list items contain the name + avatar + badges
    // Look for a more specific selector: agent list items have avatar images
    const avatarAlt = agentName;
    const avatarLocator = this.page.locator(`img[alt="${avatarAlt}"]`).first();

    if (await avatarLocator.isVisible({ timeout: 3_000 }).catch(() => false)) {
      // Click the parent row to expand
      const row = avatarLocator.locator('..').locator('..');
      await row.click();
      await this.page.waitForTimeout(500);

      // Find the LLM provider dropdown in the expanded form
      // The dropdown is a <select> element inside the expanded agent panel
      const providerSelect = this.page.locator('select').filter({
        has: this.page.locator('label').filter({ hasText: new RegExp(llmLabel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') }),
      }).first();

      // Alternative: find select by looking in the expanded panel near the label
      const expandedSelect = this.page.locator('label').filter({
        hasText: new RegExp(llmLabel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'),
      }).first().locator('..').locator('select').first();

      const targetSelect = (await providerSelect.isVisible({ timeout: 1_000 }).catch(() => false))
        ? providerSelect
        : expandedSelect;

      if (await targetSelect.isVisible({ timeout: 2_000 }).catch(() => false)) {
        await targetSelect.selectOption(String(providerId));
        await this.page.waitForTimeout(300);
      }

      // Click the row again to collapse
      await row.click();
      await this.page.waitForTimeout(300);
    }
  }

  /** Step 5: Accept default network configuration */
  async useDefaultNetwork() {
    await this.clickNext();
  }

  /** Step 6: Review and create the simulation */
  async create() {
    const createText = t('experimentBuilder.create', this.locale);
    const createBtn = this.page.getByRole('button', {
      name: new RegExp(createText, 'i'),
    });
    await createBtn.click();

    // Wait for navigation to the simulation workspace
    await this.page.waitForURL(/\/simulations\/[^/]+/, { timeout: 30_000 });
  }

  /** Run the full wizard flow with defaults for a given scenario */
  async createSimulationWithDefaults(
    scenarioId: string,
    agentNames: string[],
    enRolePrompts: string[],
    zhRolePrompts: string[],
    params?: Record<string, string | number>,
    providerIds?: number[],
  ) {
    await this.open();
    await this.selectScenario(scenarioId);
    await this.configureDefaults(params);
    await this.selectAllActions();
    await this.addAgents(agentNames, enRolePrompts, zhRolePrompts, providerIds);
    await this.useDefaultNetwork();
    await this.create();
  }

  /** Click the Next button and wait for step transition */
  private async clickNext() {
    const nextText = t('experimentBuilder.next', this.locale);
    // The "Next" button has " →" appended in the UI
    const nextBtn = this.page.getByRole('button', { name: new RegExp(nextText, 'i') });
    await nextBtn.click();
    await this.page.waitForTimeout(1000);
  }
}
