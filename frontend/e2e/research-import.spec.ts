import { test, expect } from './fixtures';
import { ensureResearchFixtureFiles, getResearchFixture } from './helpers/research-fixtures';

async function mockAnalyzeResponse(page: import('@playwright/test').Page, response: Record<string, unknown>) {
  await page.route('**/api/llm/ai_scientist/analyze', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(response),
    });
  });
}

async function mockUploadResponse(page: import('@playwright/test').Page, response: Record<string, unknown>) {
  await page.route('**/api/uploads', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(response),
    });
  });
}

async function openResearchBuilder(page: import('@playwright/test').Page, locale: string) {
  const customTitle = locale === 'zh' ? '自定义实验' : 'Custom experiment';

  await page.goto('/simulations/create');
  await page.waitForLoadState('networkidle');
  await page.getByRole('button', { name: new RegExp(customTitle, 'i') }).click();
  await page.waitForURL(/\/simulations\/create\/custom/);
}

async function waitForAnalysisToPopulate(page: import('@playwright/test').Page) {
  await expect(page.getByTestId('research-background-draft')).not.toHaveValue('', { timeout: 20_000 });
}

async function selectDeterministicRecognition(
  page: import('@playwright/test').Page,
  locale: string,
) {
  const label = locale === 'zh' ? '本地识别模式' : 'Deterministic recognition';
  await page.getByRole('button', { name: new RegExp(label, 'i') }).click();
}

async function openAdvancedReview(
  page: import('@playwright/test').Page,
  locale: string,
) {
  const label = locale === 'zh' ? '高级修改与校对' : 'Advanced edits and review';
  await page.getByRole('button', { name: new RegExp(label, 'i') }).click();
  await expect(page.getByRole('button', { name: /semantic schema|实验语义骨架/i })).toBeVisible();
}

async function openSemanticSchema(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: /semantic schema|实验语义骨架/i }).click();
  await expect(page.getByTestId('research-semantic-schema')).toBeVisible();
}

async function openValidationNotes(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: /^(validation notes|校对依据)/i }).click();
  await expect(page.getByTestId('research-source-section').first()).toBeVisible();
}

test('research import from scanned PDF reconstructs a preset-backed public goods draft', async ({ page, authedPage, locale }) => {
  const files = ensureResearchFixtureFiles('fehr_gaechter_public_goods_2000');
  await mockUploadResponse(page, {
    url: '/uploads/fehr_gaechter_public_goods_2000-scanned.pdf',
    filename: 'fehr_gaechter_public_goods_2000-scanned.pdf',
    size: 24576,
    content_type: 'application/pdf',
    extracted_text: 'Each participant receives 20 tokens and decides how many tokens to contribute to a shared public account.',
    extracted_title: 'Public Goods Study',
    extracted_abstract: 'Each participant receives 20 tokens and decides how many tokens to contribute to a shared public account.',
    extraction_method: 'ocr',
    extraction_warnings: ['Used OCR fallback because direct PDF text extraction was weak.'],
    page_count: 1,
    extracted_pages: [
      {
        page_number: 1,
        text: 'Each participant receives 20 tokens and decides how many tokens to contribute to a shared public account.',
        method: 'ocr',
        char_count: 102,
      },
    ],
    extracted_sections: [
      {
        id: 'abstract',
        title: 'Abstract',
        excerpt: 'Each participant receives 20 tokens and decides how many tokens to contribute to a shared public account.',
        page: 1,
      },
      {
        id: 'methods',
        title: 'Methods',
        excerpt: 'Groups of four repeatedly choose whether to contribute more or keep more of the endowment.',
        page: 1,
      },
    ],
    extracted_figure_captions: [],
    extracted_table_captions: [],
    extracted_document_quality: {
      section_count: 2,
      has_title: true,
      has_abstract: true,
      has_references: false,
      ocr_used: true,
      strong_extraction: true,
      average_page_quality: 0.82,
      warnings: ['Used OCR fallback because direct PDF text extraction was weak.'],
      char_count: 102,
    },
  });
  await mockAnalyzeResponse(page, {
    scenario_description: 'Participants repeatedly decide how much of a 20 token endowment to contribute to a shared public account and how much to keep privately.',
    settings: [
      { key: 'research_question', value: 'How does cooperation change when participants can contribute to a shared pool?', reason: 'Recovered from the fixture abstract.' },
    ],
    actions: [
      { name: 'contribute', description: 'Contribute some of the endowment to the shared account.' },
      { name: 'keep', description: 'Keep the endowment in a private account.' },
    ],
    agents: [
      { label: 'participants', description: 'Group members making contribution decisions.', count: 4 },
    ],
    key_variables: ['cooperation', 'punishment', 'contribution level'],
    template_suggestions: [
      {
        id: 'public_goods',
        name: 'Public Goods Game',
        category: 'game_theory',
        description: 'Shared pool contribution study.',
        score: 0.92,
        reason: 'The source describes a shared public account, endowments, and contribution choices.',
      },
    ],
    used_llm: false,
    warnings: [],
    assumptions: ['Network structure is not specified in the source and should be reviewed manually.'],
    missing_information: [],
    evidence: [
      { label: 'Action clue', snippet: 'each participant receives 20 tokens and decides how many tokens to contribute to a shared public account', section: 'Abstract' },
    ],
    recommended_scenario_id: 'public_goods',
    recommended_scenario_reason: 'The fixture closely matches the contribution-versus-keep structure of a public goods game.',
    recommended_params: {
      tokens_per_round: 20,
      multiplier: 1.6,
    },
    source_sections: [
      { id: 'abstract', title: 'Abstract', excerpt: 'Each participant receives 20 tokens and decides how many tokens to contribute to a shared public account.', page: 1 },
      { id: 'methods', title: 'Methods', excerpt: 'Groups of four repeatedly choose whether to contribute more or keep more of the endowment.', page: 1 },
    ],
    semantic_schema: {
      title: 'Public Goods Study',
      research_goal: 'Understand how cooperation changes when participants can contribute to a shared pool.',
      setting: 'Participants repeatedly receive endowments and decide how much to contribute to a public account.',
      participants: [
        { label: 'participants', description: 'Group members making contribution decisions.', count: 4 },
      ],
      decision_context: ['Participants decide how much of a 20 token endowment to contribute and how much to keep.'],
      choices: [
        { name: 'contribute', description: 'Contribute some of the endowment to the shared account.' },
        { name: 'keep', description: 'Keep the endowment in a private account.' },
      ],
      payoff_rules: ['Contributions are multiplied and redistributed across the group.'],
      constraints: [],
      information_structure: [],
      interaction_topology: [],
      interventions: [],
      outcomes: ['Cooperation', 'Contribution level'],
      key_variables: ['cooperation', 'punishment', 'contribution level'],
      source_sections: [
        { id: 'abstract', title: 'Abstract', excerpt: 'Each participant receives 20 tokens and decides how many tokens to contribute to a shared public account.', page: 1 },
      ],
      evidence_map: {},
    },
  });

  await openResearchBuilder(page, locale);
  await selectDeterministicRecognition(page, locale);
  await page.getByTestId('research-upload-input').setInputFiles(files.scannedPdfPath);

  await expect(page.getByTestId('research-source-file-card')).toContainText('fehr_gaechter_public_goods_2000-scanned.pdf', {
    timeout: 60_000,
  });
  await waitForAnalysisToPopulate(page);
  await openAdvancedReview(page, locale);
  await openSemanticSchema(page);
  await openValidationNotes(page);
  await expect(page.getByTestId('research-extraction-summary')).toContainText(/ocr|manual-text|ghostscript-text/i);
  await expect(page.getByTestId('research-page-preview').first()).toContainText(/public goods|shared public account/i);
  await expect(page.getByTestId('research-semantic-schema')).toContainText(/research goal|研究目标/i);
  await expect(
    page.getByTestId('builder-mode-recommended').getByRole('button', {
      name: /map into a preset scenario|映射到一个预设场景/i,
    }),
  ).toHaveAttribute('aria-pressed', 'true');

  await page.getByTestId('research-background-draft').fill(
    'Reviewed public goods reconstruction for builder handoff. Participants choose how much of a 20 token endowment to contribute to a shared pool.'
  );
  await page.getByTestId('research-continue-button').click();

  await page.waitForURL(/\/simulations\/create\/preset/, { timeout: 60_000 });

  // The preset page is code-split and mounts asynchronously after the URL changes.
  // While its chunk loads, the outgoing research page stays mounted and its
  // background-draft textarea is a false match for the 场景描述/scenario-description
  // name regex in zh (its zh placeholder contains 场景描述). Anchor on the preset
  // wizard's own step-2 field (id="scenario-description", Step2StarterTemplate) so
  // the assertion AND the following back-click always run against the wizard — never
  // against the stale research page's header "Back" button (which navigates to
  // /simulations/create, not back to /simulations/create/custom).
  const presetScenarioDescription = page.locator('#scenario-description');
  await expect(presetScenarioDescription).toBeVisible({ timeout: 30_000 });
  await expect(presetScenarioDescription).toHaveValue(
    /Reviewed public goods reconstruction/,
    { timeout: 30_000 },
  );

  await page.getByRole('button', { name: /back|返回/i }).first().click();
  await page.waitForURL(/\/simulations\/create\/custom/, { timeout: 60_000 });
  await expect(page.getByTestId('research-background-draft')).toHaveValue(/Reviewed public goods reconstruction/, { timeout: 30_000 });
  await openAdvancedReview(page, locale);
});

test("research import from pasted prisoner's dilemma text can be handed back as a custom scenario", async ({ page, authedPage, locale }) => {
  const fixture = getResearchFixture('rapoport_chammah_prisoners_dilemma_1965');
  await mockAnalyzeResponse(page, {
    scenario_description: "Two participants repeatedly choose between cooperation and defection without knowing the partner's current move.",
    settings: [
      { key: 'research_question', value: 'When does repeated strategic interaction sustain cooperation?', reason: 'Recovered from the abstract summary.' },
    ],
    actions: [
      { name: 'cooperate', description: 'Choose the cooperative option.' },
      { name: 'defect', description: 'Choose the self-interested option.' },
    ],
    agents: [
      { label: 'participants', description: 'Paired players making repeated binary choices.', count: 2 },
    ],
    key_variables: ['cooperation', 'retaliation', 'strategic uncertainty'],
    template_suggestions: [
      {
        id: 'prisoners_dilemma',
        name: "Prisoner's Dilemma",
        category: 'game_theory',
        description: 'Binary cooperate/defect interaction.',
        score: 0.88,
        reason: 'The source explicitly describes cooperate-versus-defect binary choices.',
      },
    ],
    used_llm: false,
    warnings: [],
    assumptions: ['Round count is not specified in the short fixture and should be reviewed manually.'],
    missing_information: [],
    evidence: [
      { label: 'Action clue', snippet: 'each participant selected either cooperate or defect without knowing the partner\'s current move', section: 'Methods' },
    ],
    recommended_scenario_id: 'prisoners_dilemma',
    recommended_scenario_reason: 'The fixture is a direct binary cooperate/defect setup.',
    recommended_params: {
      action_1: 'Cooperate',
      action_2: 'Defect',
    },
    source_sections: [
      { id: 'abstract', title: 'Abstract', excerpt: 'Pairs of participants choose between cooperation and defection in repeated play.', page: null },
      { id: 'methods', title: 'Methods', excerpt: 'Two players selected either cooperate or defect each round.', page: null },
    ],
    semantic_schema: {
      title: "Repeated Prisoner's Dilemma",
      research_goal: 'Understand when repeated strategic interaction sustains cooperation.',
      setting: "Pairs of participants repeatedly choose between cooperation and defection.",
      participants: [
        { label: 'participants', description: 'Paired players making repeated binary choices.', count: 2 },
      ],
      decision_context: ['Each round, both players choose between cooperation and defection.'],
      choices: [
        { name: 'cooperate', description: 'Choose the cooperative option.' },
        { name: 'defect', description: 'Choose the self-interested option.' },
      ],
      payoff_rules: [],
      constraints: [],
      information_structure: ["Players do not know the partner's current move."],
      interaction_topology: [],
      interventions: [],
      outcomes: ['Cooperation', 'Retaliation'],
      key_variables: ['cooperation', 'retaliation', 'strategic uncertainty'],
      source_sections: [
        { id: 'abstract', title: 'Abstract', excerpt: 'Pairs of participants choose between cooperation and defection in repeated play.', page: null },
      ],
      evidence_map: {},
    },
  });

  await openResearchBuilder(page, locale);
  await selectDeterministicRecognition(page, locale);
  await page.getByTestId('research-source-text').fill(fixture.text);
  await page.getByTestId('research-analyze-button').click();

  await waitForAnalysisToPopulate(page);
  await openAdvancedReview(page, locale);
  await openValidationNotes(page);
  await page.getByTestId('builder-mode-custom').click();
  await expect(page.getByTestId('builder-mode-custom')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('research-evidence-card').first()).toBeVisible();

  await page.getByTestId('research-background-draft').fill(
    "Reviewed prisoner's dilemma reconstruction with binary cooperate/defect choices."
  );
  await page.getByTestId('research-continue-button').click();

  await page.waitForURL(/\/simulations\/create\/preset/, { timeout: 60_000 });
  await expect(page.getByRole('textbox', { name: /custom scenario prompt|自定义场景提示/i })).toHaveValue(
    /prisoner's dilemma reconstruction/i,
    { timeout: 30_000 },
  );

  const nextButton = page.getByRole('button', { name: /next|下一步/i }).last();
  await nextButton.click();
  await expect(page.getByRole('heading', { name: /cooperate|合作/i })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('heading', { name: /defect|背叛/i })).toBeVisible({ timeout: 30_000 });
});

test('research builder clear draft resets the persisted custom draft', async ({ page, authedPage, locale }) => {
  await mockAnalyzeResponse(page, {
    scenario_description: 'A temporary draft that should be cleared.',
    settings: [{ key: 'research_question', value: 'Temporary question', reason: 'Fixture for clearing.' }],
    actions: [{ name: 'cooperate', description: 'Temporary action.' }],
    agents: [{ label: 'participants', description: 'Temporary participants.', count: 2 }],
    key_variables: ['temporary'],
    template_suggestions: [],
    used_llm: false,
    warnings: [],
    assumptions: [],
    missing_information: [],
    evidence: [{ label: 'Evidence', snippet: 'temporary snippet', section: 'Abstract' }],
    recommended_scenario_id: 'custom',
    recommended_scenario_reason: 'No preset match.',
    recommended_params: {},
    source_sections: [{ id: 'abstract', title: 'Abstract', excerpt: 'temporary snippet', page: null }],
    semantic_schema: {
      title: 'Temporary draft',
      research_goal: 'Temporary question',
      setting: 'Temporary setting.',
      participants: [{ label: 'participants', description: 'Temporary participants.', count: 2 }],
      decision_context: ['Temporary decision context.'],
      choices: [{ name: 'cooperate', description: 'Temporary action.' }],
      payoff_rules: [],
      constraints: [],
      information_structure: [],
      interaction_topology: [],
      interventions: [],
      outcomes: [],
      key_variables: ['temporary'],
      source_sections: [{ id: 'abstract', title: 'Abstract', excerpt: 'temporary snippet', page: null }],
      evidence_map: {},
    },
  });

  await openResearchBuilder(page, locale);
  await selectDeterministicRecognition(page, locale);
  await page.getByTestId('research-source-text').fill('Temporary text for clearing.');
  await page.getByTestId('research-analyze-button').click();
  await waitForAnalysisToPopulate(page);

  await page.getByRole('button', { name: /clear draft|一键清空/i }).click();
  await expect(page.getByTestId('research-source-text')).toHaveValue('');
  await expect(page.getByTestId('research-background-draft')).toHaveValue('');

  await page.reload();
  await page.waitForURL(/\/simulations\/create\/custom/, { timeout: 60_000 });
  await expect(page.getByTestId('research-source-text')).toHaveValue('');
  await expect(page.getByTestId('research-background-draft')).toHaveValue('');
});
