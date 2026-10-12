import { apiClient } from './client';
import { getApiLanguage } from './i18nUtils';

export interface AiScientistSetting {
  key: string;
  value: string;
  reason: string;
}

export interface AiScientistAction {
  name: string;
  description: string;
}

export interface AiScientistAgent {
  label: string;
  description: string;
  count: number;
}

export interface AiScientistTemplateSuggestion {
  id: string;
  name: string;
  category: string;
  description: string;
  score: number;
  reason: string;
}

export interface AiScientistEvidence {
  label: string;
  snippet: string;
  section?: string | null;
}

export interface AiScientistSourceSection {
  id: string;
  title: string;
  excerpt: string;
  page?: number | null;
}

export interface AiScientistInteractionStructure {
  type: string;
  confidence?: number;
  family?: string;
  display_label?: string;
}

export interface AiScientistOntology {
  participant_primitives?: string[];
  action_primitives?: string[];
  mechanism_primitives?: string[];
  outcome_primitives?: string[];
  structure_candidates?: string[];
}

export interface AiScientistSemanticSchema {
  title: string;
  research_goal: string;
  setting: string;
  participants: AiScientistAgent[];
  decision_context: string[];
  choices: AiScientistAction[];
  payoff_rules: string[];
  constraints: string[];
  information_structure: string[];
  interaction_topology: string[];
  interaction_structure?: AiScientistInteractionStructure;
  ontology?: AiScientistOntology;
  interventions: string[];
  outcomes: string[];
  key_variables: string[];
  source_sections: AiScientistSourceSection[];
  outline?: Record<string, unknown>;
  evidence_map?: Record<string, string[]>;
}

export interface AnalyzeAiScientistResponse {
  scenario_description: string;
  settings: AiScientistSetting[];
  actions: AiScientistAction[];
  agents: AiScientistAgent[];
  key_variables: string[];
  template_suggestions: AiScientistTemplateSuggestion[];
  used_llm: boolean;
  model_used?: string | null;
  warnings: string[];
  assumptions: string[];
  missing_information: string[];
  evidence: AiScientistEvidence[];
  evidence_by_field?: Record<string, string[]>;
  recommended_scenario_id: string;
  recommended_scenario_reason: string;
  recommendation_confidence: number;
  review_required: boolean;
  recommended_params: Record<string, unknown>;
  source_sections: AiScientistSourceSection[];
  semantic_schema: AiScientistSemanticSchema;
}

export interface AiScientistDraftSource {
  textExcerpt: string;
  fileName?: string | null;
  sections: AiScientistSourceSection[];
}

export interface AiScientistDraftScenario {
  description: string;
  recommendedScenarioId: string;
  recommendedReason: string;
  confidence: number;
  reviewRequired: boolean;
}

export interface AiScientistDraftV1 {
  version: 1;
  locale: string;
  source: AiScientistDraftSource;
  scenario: AiScientistDraftScenario;
  settings: AiScientistSetting[];
  actions: AiScientistAction[];
  agents: AiScientistAgent[];
  keyVariables: string[];
  recommendedParams: Record<string, unknown>;
  templateSuggestions: AiScientistTemplateSuggestion[];
  evidence: AiScientistEvidence[];
  evidenceByField: Record<string, string[]>;
  semanticSchema: AiScientistSemanticSchema;
  assumptions: string[];
  missingInformation: string[];
  warnings: string[];
  usedLlm: boolean;
  modelUsed?: string | null;
}

export type AiScientistRecognitionMode = 'deterministic' | 'provider';
export type AiScientistReextractField = 'scenario' | 'settings' | 'actions' | 'agents' | 'variables';

export interface ReextractAiScientistFieldResponse {
  field: AiScientistReextractField;
  scenario_description?: string | null;
  settings: AiScientistSetting[];
  actions: AiScientistAction[];
  agents: AiScientistAgent[];
  key_variables: string[];
  evidence: string[];
  warnings: string[];
}

export async function analyzeAiScientistInput(params: {
  text: string;
  recognitionMode?: AiScientistRecognitionMode;
  providerId?: number | null;
  language?: string;
  topKTemplates?: number;
  sourceFileName?: string | null;
  sourceSections?: AiScientistSourceSection[];
}): Promise<AnalyzeAiScientistResponse> {
  const payload = {
    text: params.text,
    recognition_mode: params.recognitionMode ?? 'deterministic',
    provider_id: params.providerId ?? null,
    language: params.language ?? getApiLanguage(),
    top_k_templates: params.topKTemplates ?? 3,
    source_file_name: params.sourceFileName ?? null,
    source_sections: params.sourceSections ?? null,
  };

  const response = await apiClient.post<AnalyzeAiScientistResponse>('/llm/ai_scientist/analyze', payload);
  return response.data;
}

export async function reextractAiScientistField(params: {
  text: string;
  field: AiScientistReextractField;
  language?: string;
  sourceSections?: AiScientistSourceSection[];
}): Promise<ReextractAiScientistFieldResponse> {
  const response = await apiClient.post<ReextractAiScientistFieldResponse>('/llm/ai_scientist/reextract-field', {
    text: params.text,
    field: params.field,
    language: params.language ?? getApiLanguage(),
    source_sections: params.sourceSections ?? null,
  });
  return response.data;
}

export function normalizeAiScientistDraft(
  response: AnalyzeAiScientistResponse,
  options: {
    locale?: string;
    sourceText?: string;
    sourceFileName?: string | null;
  } = {},
): AiScientistDraftV1 {
  return {
    version: 1,
    locale: options.locale ?? getApiLanguage(),
    source: {
      textExcerpt: (options.sourceText || '').trim().slice(0, 5000),
      fileName: options.sourceFileName ?? null,
      sections: response.source_sections || [],
    },
    scenario: {
      description: response.scenario_description || '',
      recommendedScenarioId: response.recommended_scenario_id || 'custom',
      recommendedReason: response.recommended_scenario_reason || '',
      confidence: response.recommendation_confidence ?? 0,
      reviewRequired: response.review_required ?? true,
    },
    settings: response.settings || [],
    actions: response.actions || [],
    agents: response.agents || [],
    keyVariables: response.key_variables || [],
    recommendedParams: response.recommended_params || {},
    templateSuggestions: response.template_suggestions || [],
    evidence: response.evidence || [],
    evidenceByField: response.evidence_by_field || {},
    semanticSchema: response.semantic_schema,
    assumptions: response.assumptions || [],
    missingInformation: response.missing_information || [],
    warnings: response.warnings || [],
    usedLlm: response.used_llm,
    modelUsed: response.model_used ?? null,
  };
}
