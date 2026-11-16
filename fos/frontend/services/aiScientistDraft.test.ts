import { describe, expect, it } from 'vitest';
import {
  AnalyzeAiScientistResponse,
  normalizeAiScientistDraft,
} from './aiScientist';

const baseSemanticSchema: AnalyzeAiScientistResponse['semantic_schema'] = {
  title: 'Contribution Study',
  research_goal: 'Study contribution behavior',
  setting: 'Lab experiment',
  participants: [{ label: 'Participant', description: 'Decision maker', count: 4 }],
  decision_context: ['Allocate tokens'],
  choices: [{ name: 'contribute', description: 'Contribute to the group account' }],
  payoff_rules: ['Group account is multiplied and shared.'],
  constraints: [],
  information_structure: [],
  interaction_topology: [],
  interventions: [],
  outcomes: ['Contribution level'],
  key_variables: ['contribution'],
  source_sections: [],
};

describe('normalizeAiScientistDraft', () => {
  it('maps the existing analyze response into the shared draft v1 shape', () => {
    const response: AnalyzeAiScientistResponse = {
      scenario_description: 'Participants decide how many tokens to contribute.',
      settings: [{ key: 'tokens_per_round', value: '10', reason: 'Mentioned in source' }],
      actions: [{ name: 'contribute', description: 'Allocate tokens to the public pool' }],
      agents: [{ label: 'Participant', description: 'Human subject role', count: 4 }],
      key_variables: ['contribution'],
      template_suggestions: [{
        id: 'public_goods',
        name: 'Public Goods Game',
        category: 'game_theory',
        description: 'Contribution dilemma',
        score: 0.9,
        reason: 'Matches contribution/public pool structure',
      }],
      used_llm: false,
      model_used: null,
      warnings: ['Ran deterministic recognition mode without provider assistance.'],
      assumptions: ['Agents understand token allocation.'],
      missing_information: [],
      evidence: [{ label: 'Contribution', snippet: 'contribute tokens', section: null }],
      evidence_by_field: { actions: ['contribute tokens'] },
      recommended_scenario_id: 'public_goods',
      recommended_scenario_reason: 'Matches public goods incentives.',
      recommendation_confidence: 0.9,
      review_required: false,
      recommended_params: { tokens_per_round: 10 },
      source_sections: [{ id: 's1', title: 'Methods', excerpt: 'contribute tokens', page: 2 }],
      semantic_schema: baseSemanticSchema,
    };

    const draft = normalizeAiScientistDraft(response, {
      locale: 'en',
      sourceText: '  Participants contribute tokens to a public pool.  ',
      sourceFileName: 'paper.pdf',
    });

    expect(draft).toMatchObject({
      version: 1,
      locale: 'en',
      source: {
        textExcerpt: 'Participants contribute tokens to a public pool.',
        fileName: 'paper.pdf',
      },
      scenario: {
        description: response.scenario_description,
        recommendedScenarioId: 'public_goods',
        confidence: 0.9,
        reviewRequired: false,
      },
      keyVariables: ['contribution'],
      recommendedParams: { tokens_per_round: 10 },
      usedLlm: false,
    });
    expect(draft.source.sections).toHaveLength(1);
    expect(draft.semanticSchema.title).toBe('Contribution Study');
  });
});
