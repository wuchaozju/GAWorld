import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  ArrowRight,
  BrainCircuit,
  ChevronDown,
  Check,
  FileSearch,
  Quote,
  RotateCcw,
  ScanSearch,
  Sparkles,
  Upload,
} from 'lucide-react';

import { Button } from '../components/ui/button';
import "../styles/routes/experiment-setup.css";
import { Card } from '../components/ui/card';
import {
  ActionsDraftPanel,
  AgentsDraftPanel,
  type DraftItem,
  type SettingDraft,
  SettingsDraftPanel,
} from '../components/experiment/AiScientistDraftPanels';
import {
  getAllScenarios,
  getScenario,
  type ActionDef,
  type ScenarioData,
} from '../services/scenarios';
import {
  analyzeAiScientistInput,
  type AiScientistRecognitionMode,
  type AnalyzeAiScientistResponse,
  type AiScientistAgent,
  type AiScientistAction,
  type AiScientistReextractField,
  type AiScientistSemanticSchema,
  type AiScientistSetting,
  type AiScientistTemplateSuggestion,
  reextractAiScientistField,
} from '../services/aiScientist';
import { listProviders, type Provider } from '../services/providers';
import { uploadImage } from '../services/uploads';
import type { UploadedAsset } from '../types';
import { useExperimentBuilder, type ManualAgentType } from '../store/experiment-builder';

interface VariableDraft {
  id: string;
  value: string;
}

type BuilderMode = 'custom' | 'recommended';
const CUSTOM_BUILDER_DRAFT_STORAGE_KEY = 'fos:research-custom-builder-draft:v1';

interface PersistedResearchDraft {
  researchText: string;
  sourceFileName: string;
  scenarioName: string;
  saveAsPresetTemplate: boolean;
  backgroundDraft: string;
  analyzedBackgroundDraft: string;
  settingsDrafts: SettingDraft[];
  extractedSettingsDrafts: SettingDraft[];
  actionDrafts: DraftItem[];
  extractedActionDrafts: DraftItem[];
  agentDrafts: DraftItem[];
  extractedAgentDrafts: DraftItem[];
  variableDrafts: VariableDraft[];
  extractedVariableValues: string[];
  templateSuggestions: AiScientistTemplateSuggestion[];
  suggestedTemplate: AiScientistTemplateSuggestion | null;
  selectedTemplateId: string | null;
  analysisWarnings: string[];
  assumptions: string[];
  missingInformation: string[];
  evidence: AnalyzeAiScientistResponse['evidence'];
  evidenceByField: Record<string, string[]>;
  sourceSections: AnalyzeAiScientistResponse['source_sections'];
  semanticSchema: AnalyzeAiScientistResponse['semantic_schema'] | null;
  sourceAsset: UploadedAsset | null;
  recommendedScenarioId: string;
  recommendedScenarioReason: string;
  recommendationConfidence: number;
  reviewRequired: boolean;
  recommendedParams: Record<string, unknown>;
  builderMode: BuilderMode;
  recognitionMode: AiScientistRecognitionMode;
  selectedProviderId: number | null;
}

const createId = (prefix: string): string => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const makeSettingDraft = (setting: AnalyzeAiScientistResponse['settings'][number]): SettingDraft => ({
  id: createId('setting'),
  key: setting.key || '',
  value: setting.value || '',
  reason: setting.reason || '',
});

const cloneSettingDraft = (draft: SettingDraft): SettingDraft => ({
  id: createId('setting'),
  key: draft.key || '',
  value: draft.value || '',
  reason: draft.reason || '',
});

const makeActionDraft = (action: AnalyzeAiScientistResponse['actions'][number]): DraftItem => ({
  id: createId('action'),
  label: action.name || '',
  description: action.description || '',
  selected: true,
});

const makeAgentDraft = (agent: AnalyzeAiScientistResponse['agents'][number]): DraftItem => ({
  id: createId('agent'),
  label: agent.label || '',
  description: agent.description || '',
  selected: true,
  count: Math.max(1, Number(agent.count || 1)),
});

const cloneDraftItem = (draft: DraftItem, prefix: 'action' | 'agent'): DraftItem => ({
  ...draft,
  id: createId(prefix),
});

const normalizeKey = (value: string): string =>
  value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');

const normalizeToken = (value: string): string => value.trim().toLowerCase();

const CUSTOM_RUNTIME_ACTIONS: ActionDef[] = [
  { id: 'speak', name: 'Speak', description: 'Say something to the group' },
  { id: 'skip', name: 'Skip', description: 'Pass without speaking this turn' },
];

const getScenarioRuntimeActions = (scenario: ScenarioData): ActionDef[] => {
  if (scenario.actions?.length) {
    return scenario.actions;
  }

  const categoryActions = scenario.category_actions || [];
  if (categoryActions.length === 0) {
    return [];
  }

  const defaultActionIds = new Set(
    (scenario.default_action_ids || []).map((value) => normalizeToken(String(value))),
  );
  if (defaultActionIds.size === 0) {
    return categoryActions;
  }

  const filtered = categoryActions.filter((action) => {
    const actionId = normalizeToken(String(action.id || ''));
    const actionName = normalizeToken(String(action.name || ''));
    return defaultActionIds.has(actionId) || defaultActionIds.has(actionName);
  });

  return filtered.length > 0 ? filtered : categoryActions;
};

const resolveRecommendedScenarioActions = (
  scenario: ScenarioData,
  approvedActions: Array<{ name: string; description: string }>,
): { availableActions: ActionDef[]; selectedActionIds: string[] } => {
  const availableActions = getScenarioRuntimeActions(scenario);
  if (availableActions.length === 0) {
    return {
      availableActions: approvedActions,
      selectedActionIds: approvedActions.map((item) => item.name),
    };
  }

  const actionLookup = new Map<string, ActionDef>();
  availableActions.forEach((action) => {
    [action.id, action.name, action.description].forEach((candidate) => {
      const key = normalizeToken(String(candidate || ''));
      if (key && !actionLookup.has(key)) {
        actionLookup.set(key, action);
      }
    });
  });

  const matchedActionNames = approvedActions
    .flatMap((item) => {
      const match = [item.name, item.description]
        .map((candidate) => actionLookup.get(normalizeToken(candidate)))
        .find(Boolean);
      return match ? [match.name] : [];
    });

  const dedupedMatchedActionNames = Array.from(new Set(matchedActionNames));
  if (dedupedMatchedActionNames.length > 0) {
    return {
      availableActions,
      selectedActionIds: dedupedMatchedActionNames,
    };
  }

  const defaultActionIds = new Set(
    (scenario.default_action_ids || []).map((value) => normalizeToken(String(value))),
  );
  const defaultSelectedActionNames = availableActions
    .filter((action) => {
      const actionId = normalizeToken(String(action.id || ''));
      const actionName = normalizeToken(String(action.name || ''));
      return defaultActionIds.has(actionId) || defaultActionIds.has(actionName);
    })
    .map((action) => action.name);

  return {
    availableActions,
    selectedActionIds: defaultSelectedActionNames.length > 0
      ? defaultSelectedActionNames
      : availableActions.map((action) => action.name),
  };
};

const buildScenarioParams = (
  settingsDrafts: SettingDraft[],
  variableDrafts: VariableDraft[],
  assumptions: string[],
  missingInformation: string[],
  evidence: AnalyzeAiScientistResponse['evidence'],
  sourceSections: AnalyzeAiScientistResponse['source_sections'],
  semanticSchema: AnalyzeAiScientistResponse['semantic_schema'] | null,
  sourceFileName: string,
  sourceText: string,
  recommendedParams: Record<string, unknown>,
) => {
  const params: Record<string, unknown> = {
    ...recommendedParams,
    ai_scientist_settings: settingsDrafts
      .map((draft) => ({
        key: draft.key.trim(),
        value: draft.value.trim(),
        reason: draft.reason.trim(),
      }))
      .filter((item) => item.key.length > 0),
    ai_scientist_key_variables: variableDrafts.map((draft) => draft.value.trim()).filter(Boolean),
    ai_scientist_assumptions: assumptions.filter(Boolean),
    ai_scientist_missing_information: missingInformation.filter(Boolean),
    ai_scientist_evidence: evidence,
    ai_scientist_source_sections: sourceSections,
    ai_scientist_semantic_schema: semanticSchema,
    research_question: sourceText.trim(),
    ai_scientist_source_file_name: sourceFileName || null,
    ai_scientist_source_excerpt: sourceText.trim().slice(0, 5000),
  };

  settingsDrafts.forEach((draft) => {
    const key = draft.key.trim();
    if (key) {
      params[key] = draft.value;
    }
  });

  return params;
};

const buildActionsForStore = (
  actionDrafts: DraftItem[],
): Array<{ name: string; description: string }> =>
  actionDrafts
    .filter((draft) => draft.selected && draft.label.trim())
    .map((draft) => ({
      name: normalizeKey(draft.label) || draft.label.trim(),
      description: draft.description.trim() || draft.label.trim(),
    }));

const buildAgentsForStore = (agentDrafts: DraftItem[]): ManualAgentType[] =>
  agentDrafts
    .filter((draft) => draft.selected && draft.label.trim())
    .map((draft) => ({
      id: draft.id,
      label: draft.label.trim(),
      count: Math.max(1, Number(draft.count || 1)),
      rolePrompt: draft.description.trim() || draft.label.trim(),
      userProfile: draft.description.trim() || draft.label.trim(),
      properties: { source: 'ai-scientist' },
      providerId: null,
    }));

const isSupportedFile = (file: File): boolean => {
  const allowedTypes = new Set([
    'text/plain',
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  ]);
  const extension = file.name.split('.').pop()?.toLowerCase() || '';
  return allowedTypes.has(file.type) || ['txt', 'pdf', 'doc', 'docx'].includes(extension);
};

const suggestedTemplateForScenario = (
  templateSuggestions: AiScientistTemplateSuggestion[],
  scenarioId: string | null,
): AiScientistTemplateSuggestion | null => {
  if (!scenarioId) return templateSuggestions[0] || null;
  return templateSuggestions.find((item) => item.id === scenarioId) || templateSuggestions[0] || null;
};

const localizedExtractionMethod = (
  method: string | null | undefined,
  t: (key: string, options?: any) => string,
): string => {
  switch ((method || '').toLowerCase()) {
    case 'ocr':
      return t('createExperiment.customBuilder.extractionMethodOcr', { defaultValue: 'OCR' });
    case 'manual-text':
      return t('createExperiment.customBuilder.extractionMethodManual', { defaultValue: 'Manual text' });
    case 'ghostscript-text':
    case 'pdf-text':
      return t('createExperiment.customBuilder.extractionMethodPdf', { defaultValue: 'PDF text extraction' });
    default:
      return method || t('createExperiment.customBuilder.extractionMethodUnknown', { defaultValue: 'Text extraction' });
  }
};

const hasSemanticSchemaContent = (schema: AiScientistSemanticSchema | null): boolean => {
  if (!schema) return false;
  return Boolean(
    schema.title ||
    schema.research_goal ||
    schema.setting ||
    schema.participants?.length ||
    schema.decision_context?.length ||
    schema.choices?.length ||
    schema.payoff_rules?.length ||
    schema.constraints?.length ||
    schema.information_structure?.length ||
    schema.interaction_topology?.length ||
    schema.interventions?.length ||
    schema.outcomes?.length ||
    schema.key_variables?.length,
  );
};

const dedupeStrings = (values: Array<string | null | undefined>, limit = 4): string[] => {
  const seen = new Set<string>();
  const results: string[] = [];
  values.forEach((value) => {
    const trimmed = String(value || '').trim();
    if (!trimmed) return;
    const key = trimmed.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    results.push(trimmed);
  });
  return results.slice(0, limit);
};

const stripFileExtension = (value: string): string => value.replace(/\.[a-z0-9]+$/i, '').trim();

const deriveScenarioName = (
  t: (key: string, options?: any) => string,
  result: Partial<AnalyzeAiScientistResponse>,
  sourceFileName?: string | null,
): string => {
  const semanticTitle = String(result.semantic_schema?.title || '').trim();
  if (semanticTitle) return semanticTitle;

  const templateName = String(result.template_suggestions?.[0]?.name || '').trim();
  if (templateName && result.recommended_scenario_id && result.recommended_scenario_id !== 'custom') {
    return templateName;
  }

  const scenarioLead = String(result.scenario_description || '').trim().split(/[.!?\n]/)[0]?.trim() || '';
  if (scenarioLead) {
    return scenarioLead.length > 72 ? `${scenarioLead.slice(0, 69).trim()}...` : scenarioLead;
  }

  const sourceName = stripFileExtension(String(sourceFileName || ''));
  if (sourceName) return sourceName;

  return t('createExperiment.customBuilder.scenarioName', { defaultValue: 'Custom AI-generated scenario' });
};

interface CollapsibleCardSectionProps {
  title: string;
  hint?: string;
  badge?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
  testId?: string;
}

function CollapsibleCardSection({
  title,
  hint,
  badge,
  defaultOpen = false,
  children,
  testId,
}: CollapsibleCardSectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    setOpen(defaultOpen);
  }, [defaultOpen]);

  return (
    <Card className="p-0" data-testid={testId}>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left"
      >
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold" style={{ color: 'var(--ss-heading)' }}>
              {title}
            </h2>
            {badge}
          </div>
          {hint ? (
            <p className="mt-1 text-sm" style={{ color: 'var(--ss-text)' }}>
              {hint}
            </p>
          ) : null}
        </div>
        <ChevronDown
          size={18}
          className={`shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
          style={{ color: 'var(--ss-text-muted)' }}
        />
      </button>

      {open ? <div className="px-5 pb-5">{children}</div> : null}
    </Card>
  );
}

const emptyResearchDraft = (): PersistedResearchDraft => ({
  researchText: '',
  sourceFileName: '',
  scenarioName: '',
  saveAsPresetTemplate: false,
  backgroundDraft: '',
  analyzedBackgroundDraft: '',
  settingsDrafts: [],
  extractedSettingsDrafts: [],
  actionDrafts: [],
  extractedActionDrafts: [],
  agentDrafts: [],
  extractedAgentDrafts: [],
  variableDrafts: [],
  extractedVariableValues: [],
  templateSuggestions: [],
  suggestedTemplate: null,
  selectedTemplateId: null,
  analysisWarnings: [],
  assumptions: [],
  missingInformation: [],
  evidence: [],
  evidenceByField: {},
  sourceSections: [],
  semanticSchema: null,
  sourceAsset: null,
  recommendedScenarioId: 'custom',
  recommendedScenarioReason: '',
  recommendationConfidence: 0,
  reviewRequired: true,
  recommendedParams: {},
  builderMode: 'custom',
  recognitionMode: 'provider',
  selectedProviderId: null,
});

export function CreateExperimentCustomPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const reset = useExperimentBuilder((state) => state.reset);
  const setCurrentStep = useExperimentBuilder((state) => state.setCurrentStep);
  const markStepComplete = useExperimentBuilder((state) => state.markStepComplete);
  const setSelectedScenarioId = useExperimentBuilder((state) => state.setSelectedScenarioId);
  const setSelectedScenarioData = useExperimentBuilder((state) => state.setSelectedScenarioData);
  const setScenarioDescription = useExperimentBuilder((state) => state.setScenarioDescription);
  const setScenarioParams = useExperimentBuilder((state) => state.setScenarioParams);
  const setAvailableActions = useExperimentBuilder((state) => state.setAvailableActions);
  const setSelectedActionIds = useExperimentBuilder((state) => state.setSelectedActionIds);
  const setAgentMode = useExperimentBuilder((state) => state.setAgentMode);
  const addAgentType = useExperimentBuilder((state) => state.addAgentType);
  const setTurnOrder = useExperimentBuilder((state) => state.setTurnOrder);
  const setRoundVisibility = useExperimentBuilder((state) => state.setRoundVisibility);
  const setSocialNetwork = useExperimentBuilder((state) => state.setSocialNetwork);

  const [researchText, setResearchText] = useState('');
  const [sourceFileName, setSourceFileName] = useState('');
  const [scenarioName, setScenarioName] = useState('');
  const [saveAsPresetTemplate, setSaveAsPresetTemplate] = useState(false);
  const [backgroundDraft, setBackgroundDraft] = useState('');
  const [analyzedBackgroundDraft, setAnalyzedBackgroundDraft] = useState('');
  const [settingsDrafts, setSettingsDrafts] = useState<SettingDraft[]>([]);
  const [extractedSettingsDrafts, setExtractedSettingsDrafts] = useState<SettingDraft[]>([]);
  const [actionDrafts, setActionDrafts] = useState<DraftItem[]>([]);
  const [extractedActionDrafts, setExtractedActionDrafts] = useState<DraftItem[]>([]);
  const [agentDrafts, setAgentDrafts] = useState<DraftItem[]>([]);
  const [extractedAgentDrafts, setExtractedAgentDrafts] = useState<DraftItem[]>([]);
  const [variableDrafts, setVariableDrafts] = useState<VariableDraft[]>([]);
  const [extractedVariableValues, setExtractedVariableValues] = useState<string[]>([]);
  const [templateSuggestions, setTemplateSuggestions] = useState<AiScientistTemplateSuggestion[]>([]);
  const [suggestedTemplate, setSuggestedTemplate] = useState<AiScientistTemplateSuggestion | null>(null);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [analysisWarnings, setAnalysisWarnings] = useState<string[]>([]);
  const [assumptions, setAssumptions] = useState<string[]>([]);
  const [missingInformation, setMissingInformation] = useState<string[]>([]);
  const [evidence, setEvidence] = useState<AnalyzeAiScientistResponse['evidence']>([]);
  const [evidenceByField, setEvidenceByField] = useState<Record<string, string[]>>({});
  const [sourceSections, setSourceSections] = useState<AnalyzeAiScientistResponse['source_sections']>([]);
  const [semanticSchema, setSemanticSchema] = useState<AnalyzeAiScientistResponse['semantic_schema'] | null>(null);
  const [sourceAsset, setSourceAsset] = useState<UploadedAsset | null>(null);
  const [recommendedScenarioId, setRecommendedScenarioId] = useState<string>('custom');
  const [recommendedScenarioReason, setRecommendedScenarioReason] = useState('');
  const [recommendationConfidence, setRecommendationConfidence] = useState(0);
  const [reviewRequired, setReviewRequired] = useState(true);
  const [recommendedParams, setRecommendedParams] = useState<Record<string, unknown>>({});
  const [builderMode, setBuilderMode] = useState<BuilderMode>('custom');
  const [recognitionMode, setRecognitionMode] = useState<AiScientistRecognitionMode>('provider');
  const [selectedProviderId, setSelectedProviderId] = useState<number | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [repairingField, setRepairingField] = useState<AiScientistReextractField | null>(null);
  const [showRecommendedTemplateDetails, setShowRecommendedTemplateDetails] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const providersQuery = useQuery({
    queryKey: ['providers'],
    queryFn: listProviders,
  });
  const scenariosQuery = useQuery({
    queryKey: ['all-scenarios'],
    queryFn: getAllScenarios,
  });
  const providers = providersQuery.data ?? [];
  const allScenarios = scenariosQuery.data ?? [];
  const configuredProviders = useMemo(() => providers.filter((provider) => provider.model), [providers]);
  const defaultProvider = useMemo(
    () => configuredProviders.find((provider) => provider.is_default || provider.is_active) ?? configuredProviders[0] ?? null,
    [configuredProviders],
  );
  const selectedProvider = useMemo(
    () => configuredProviders.find((provider) => provider.id === selectedProviderId) ?? null,
    [configuredProviders, selectedProviderId],
  );

  const selectedActionDrafts = useMemo(
    () => actionDrafts.filter((draft) => draft.selected && draft.label.trim()),
    [actionDrafts],
  );
  const selectedAgentDrafts = useMemo(
    () => agentDrafts.filter((draft) => draft.selected && draft.label.trim()),
    [agentDrafts],
  );
  const sourcePages = sourceAsset?.extracted_pages ?? [];
  const sourceDiagnostics = sourceAsset?.extraction_warnings ?? [];
  const sourceDocumentQuality = sourceAsset?.extracted_document_quality ?? null;
  const modeSummary = recognitionMode === 'deterministic'
    ? t('createExperiment.customBuilder.modeDeterministicShort', { defaultValue: '本地后端识别，无需 Provider，不消耗 token，但复杂论文识别能力有限。' })
    : t('createExperiment.customBuilder.modeProviderShort', { defaultValue: '调用已配置模型进行智能识别，模板判断与草案生成更强，但会消耗相应 token 或本地推理资源。' });

  const clearDraft = () => {
    const empty = emptyResearchDraft();
    setResearchText(empty.researchText);
    setSourceFileName(empty.sourceFileName);
    setScenarioName(empty.scenarioName);
    setSaveAsPresetTemplate(empty.saveAsPresetTemplate);
    setBackgroundDraft(empty.backgroundDraft);
    setAnalyzedBackgroundDraft(empty.analyzedBackgroundDraft);
    setSettingsDrafts(empty.settingsDrafts);
    setExtractedSettingsDrafts(empty.extractedSettingsDrafts);
    setActionDrafts(empty.actionDrafts);
    setExtractedActionDrafts(empty.extractedActionDrafts);
    setAgentDrafts(empty.agentDrafts);
    setExtractedAgentDrafts(empty.extractedAgentDrafts);
    setVariableDrafts(empty.variableDrafts);
    setExtractedVariableValues(empty.extractedVariableValues);
    setTemplateSuggestions(empty.templateSuggestions);
    setSuggestedTemplate(empty.suggestedTemplate);
    setSelectedTemplateId(empty.selectedTemplateId);
    setAnalysisWarnings(empty.analysisWarnings);
    setAssumptions(empty.assumptions);
    setMissingInformation(empty.missingInformation);
    setEvidence(empty.evidence);
    setEvidenceByField(empty.evidenceByField);
    setSourceSections(empty.sourceSections);
    setSemanticSchema(empty.semanticSchema);
    setSourceAsset(empty.sourceAsset);
    setRecommendedScenarioId(empty.recommendedScenarioId);
    setRecommendedScenarioReason(empty.recommendedScenarioReason);
    setRecommendationConfidence(empty.recommendationConfidence);
    setReviewRequired(empty.reviewRequired);
    setRecommendedParams(empty.recommendedParams);
    setBuilderMode(empty.builderMode);
    setRecognitionMode(empty.recognitionMode);
    setSelectedProviderId(empty.selectedProviderId);
    setShowRecommendedTemplateDetails(false);
    setErrorMessage('');
    window.sessionStorage.removeItem(CUSTOM_BUILDER_DRAFT_STORAGE_KEY);
  };

  useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(CUSTOM_BUILDER_DRAFT_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as PersistedResearchDraft;
      setResearchText(parsed.researchText || '');
      setSourceFileName(parsed.sourceFileName || '');
      setScenarioName(parsed.scenarioName || '');
      setSaveAsPresetTemplate(Boolean(parsed.saveAsPresetTemplate));
      setBackgroundDraft(parsed.backgroundDraft || '');
      setAnalyzedBackgroundDraft(parsed.analyzedBackgroundDraft || '');
      setSettingsDrafts(parsed.settingsDrafts || []);
      setExtractedSettingsDrafts(parsed.extractedSettingsDrafts || []);
      setActionDrafts(parsed.actionDrafts || []);
      setExtractedActionDrafts(parsed.extractedActionDrafts || []);
      setAgentDrafts(parsed.agentDrafts || []);
      setExtractedAgentDrafts(parsed.extractedAgentDrafts || []);
      setVariableDrafts(parsed.variableDrafts || []);
      setExtractedVariableValues(parsed.extractedVariableValues || []);
      setTemplateSuggestions(parsed.templateSuggestions || (parsed.suggestedTemplate ? [parsed.suggestedTemplate] : []));
      setSuggestedTemplate(parsed.suggestedTemplate || null);
      setSelectedTemplateId(parsed.selectedTemplateId || parsed.suggestedTemplate?.id || null);
      setAnalysisWarnings(parsed.analysisWarnings || []);
      setAssumptions(parsed.assumptions || []);
      setMissingInformation(parsed.missingInformation || []);
      setEvidence(parsed.evidence || []);
      setEvidenceByField(parsed.evidenceByField || {});
      setSourceSections(parsed.sourceSections || []);
      setSemanticSchema(parsed.semanticSchema || null);
      setSourceAsset(parsed.sourceAsset || null);
      setRecommendedScenarioId(parsed.recommendedScenarioId || 'custom');
      setRecommendedScenarioReason(parsed.recommendedScenarioReason || '');
      setRecommendationConfidence(parsed.recommendationConfidence || 0);
      setReviewRequired(parsed.reviewRequired ?? true);
      setRecommendedParams(parsed.recommendedParams || {});
      setBuilderMode(parsed.builderMode || 'custom');
      setRecognitionMode(parsed.recognitionMode || 'provider');
      setSelectedProviderId(parsed.selectedProviderId ?? null);
    } catch {
      window.sessionStorage.removeItem(CUSTOM_BUILDER_DRAFT_STORAGE_KEY);
    }
  }, []);

  useEffect(() => {
    try {
      const payload: PersistedResearchDraft = {
        researchText,
        sourceFileName,
        scenarioName,
        saveAsPresetTemplate,
        backgroundDraft,
        analyzedBackgroundDraft,
        settingsDrafts,
        extractedSettingsDrafts,
        actionDrafts,
        extractedActionDrafts,
        agentDrafts,
        extractedAgentDrafts,
        variableDrafts,
        extractedVariableValues,
        templateSuggestions,
        suggestedTemplate,
        selectedTemplateId,
        analysisWarnings,
        assumptions,
        missingInformation,
        evidence,
        evidenceByField,
        sourceSections,
        semanticSchema,
        sourceAsset,
        recommendedScenarioId,
        recommendedScenarioReason,
        recommendationConfidence,
        reviewRequired,
        recommendedParams,
        builderMode,
        recognitionMode,
        selectedProviderId,
      };
      window.sessionStorage.setItem(CUSTOM_BUILDER_DRAFT_STORAGE_KEY, JSON.stringify(payload));
    } catch {
      // Ignore storage quota or serialization failures and keep the in-memory draft.
    }
  }, [
    researchText,
    sourceFileName,
    scenarioName,
    saveAsPresetTemplate,
    backgroundDraft,
    analyzedBackgroundDraft,
    settingsDrafts,
    extractedSettingsDrafts,
    actionDrafts,
    extractedActionDrafts,
    agentDrafts,
    extractedAgentDrafts,
    variableDrafts,
    extractedVariableValues,
    templateSuggestions,
    suggestedTemplate,
    selectedTemplateId,
    analysisWarnings,
    assumptions,
    missingInformation,
    evidence,
    evidenceByField,
    sourceSections,
    semanticSchema,
    sourceAsset,
    recommendedScenarioId,
    recommendedScenarioReason,
    recommendationConfidence,
    reviewRequired,
    recommendedParams,
    builderMode,
    recognitionMode,
    selectedProviderId,
  ]);

  useEffect(() => {
    if (!configuredProviders.length) {
      setSelectedProviderId(null);
      return;
    }
    if (selectedProviderId && configuredProviders.some((provider) => provider.id === selectedProviderId)) {
      return;
    }
    setSelectedProviderId(defaultProvider?.id ?? configuredProviders[0]?.id ?? null);
  }, [configuredProviders, defaultProvider, selectedProviderId]);

  const syncAnalysis = (result: AnalyzeAiScientistResponse, sourceName?: string) => {
    const extractedScenario = result.scenario_description || researchText.trim();
    const extractedName = deriveScenarioName(t, result, sourceName || sourceFileName);
    const extractedSettings = (result.settings || []).map(makeSettingDraft);
    const extractedActions = (result.actions || []).map(makeActionDraft);
    const extractedAgents = (result.agents || []).map(makeAgentDraft);
    const extractedVariables = (result.key_variables || []).filter((value) => value.trim());

    setBackgroundDraft(extractedScenario);
    setAnalyzedBackgroundDraft(extractedScenario);
    setScenarioName(extractedName);
    setSettingsDrafts(extractedSettings.map(cloneSettingDraft));
    setExtractedSettingsDrafts(extractedSettings);
    setActionDrafts(extractedActions.map((draft) => cloneDraftItem(draft, 'action')));
    setExtractedActionDrafts(extractedActions);
    setAgentDrafts(extractedAgents.map((draft) => cloneDraftItem(draft, 'agent')));
    setExtractedAgentDrafts(extractedAgents);
    setVariableDrafts(extractedVariables.map((value) => ({ id: createId('variable'), value })));
    setExtractedVariableValues(extractedVariables);
    setTemplateSuggestions(result.template_suggestions || []);
    setSuggestedTemplate(suggestedTemplateForScenario(result.template_suggestions, result.recommended_scenario_id));
    const fallbackSelectedTemplate = suggestedTemplateForScenario(result.template_suggestions, result.recommended_scenario_id);
    setSelectedTemplateId(result.recommended_scenario_id !== 'custom' ? result.recommended_scenario_id : fallbackSelectedTemplate?.id || null);
    setAnalysisWarnings(result.warnings || []);
    setAssumptions(result.assumptions || []);
    setMissingInformation(result.missing_information || []);
    setEvidence(result.evidence || []);
    setEvidenceByField(result.evidence_by_field || {});
    setSourceSections(result.source_sections || []);
    setSemanticSchema(result.semantic_schema || null);
    setRecommendedScenarioId(result.recommended_scenario_id || 'custom');
    setRecommendedScenarioReason(result.recommended_scenario_reason || '');
    setRecommendationConfidence(result.recommendation_confidence || 0);
    setReviewRequired(Boolean(result.review_required));
    setRecommendedParams(result.recommended_params || {});
    setBuilderMode(result.recommended_scenario_id && result.recommended_scenario_id !== 'custom' ? 'recommended' : 'custom');
    setShowRecommendedTemplateDetails(false);
    if (sourceName) {
      setSourceFileName(sourceName);
    }
  };

  const runAnalysis = async (
    text: string,
    options?: {
      sourceSections?: AnalyzeAiScientistResponse['source_sections'];
      sourceFileName?: string;
    },
  ) => {
    const trimmed = text.trim();
    if (!trimmed) {
      setErrorMessage(t('createExperiment.customBuilder.enterTextFirst', { defaultValue: 'Enter text or upload a file before analyzing.' }));
      return;
    }
    if (recognitionMode === 'provider' && !selectedProviderId) {
      setErrorMessage(t('createExperiment.customBuilder.providerRequired', { defaultValue: 'Select a configured model before running provider-powered recognition.' }));
      return;
    }

    setIsAnalyzing(true);
    setErrorMessage('');

    try {
      const result = await analyzeAiScientistInput({
        text: trimmed,
        recognitionMode,
        providerId: recognitionMode === 'provider' ? selectedProviderId : null,
        topKTemplates: 5,
        language: i18n.language,
        sourceFileName: options?.sourceFileName || sourceFileName || null,
        sourceSections: options?.sourceSections || sourceSections,
      });
      setResearchText(trimmed);
      syncAnalysis(result, options?.sourceFileName);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t('createExperiment.customBuilder.analysisFailed', { defaultValue: 'Failed to analyze the text.' }));
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileSelected = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';

    if (!file) return;
    if (!isSupportedFile(file)) {
      setErrorMessage(t('createExperiment.customBuilder.uploadFileTypeError', { defaultValue: 'Upload a .txt, .pdf, .doc, or .docx file.' }));
      return;
    }

    setIsUploading(true);
    setErrorMessage('');

    try {
      const uploaded = await uploadImage(file, { ocr: true });
      const extracted = (uploaded.extracted_text || '').trim();
      if (!extracted) {
        throw new Error(t('createExperiment.customBuilder.uploadNoText', { defaultValue: 'No readable text was extracted from the uploaded file.' }));
      }

      setSourceAsset(uploaded);
      setResearchText(extracted);
      setSourceFileName(file.name);
      await runAnalysis(extracted, { sourceSections: uploaded.extracted_sections || [], sourceFileName: file.name });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t('createExperiment.customBuilder.uploadFailed', { defaultValue: 'File upload failed.' }));
    } finally {
      setIsUploading(false);
    }
  };

  const addVariable = () => setVariableDrafts((current) => [...current, { id: createId('variable'), value: '' }]);
  const updateVariable = (id: string, value: string) => setVariableDrafts((current) => current.map((draft) => (draft.id === id ? { ...draft, value } : draft)));
  const removeVariable = (id: string) => setVariableDrafts((current) => current.filter((draft) => draft.id !== id));
  const addSetting = () => setSettingsDrafts((current) => [...current, { id: createId('setting'), key: '', value: '', reason: '' }]);
  const updateSetting = (id: string, updates: Partial<SettingDraft>) => setSettingsDrafts((current) => current.map((draft) => (draft.id === id ? { ...draft, ...updates } : draft)));
  const removeSetting = (id: string) => setSettingsDrafts((current) => current.filter((draft) => draft.id !== id));
  const addAction = () => setActionDrafts((current) => [...current, { id: createId('action'), label: '', description: '', selected: true }]);
  const updateAction = (id: string, updates: Partial<DraftItem>) => setActionDrafts((current) => current.map((draft) => (draft.id === id ? { ...draft, ...updates } : draft)));
  const removeAction = (id: string) => setActionDrafts((current) => current.filter((draft) => draft.id !== id));
  const addAgent = () => setAgentDrafts((current) => [...current, { id: createId('agent'), label: '', description: '', selected: true, count: 1 }]);
  const updateAgent = (id: string, updates: Partial<DraftItem>) => setAgentDrafts((current) => current.map((draft) => (draft.id === id ? { ...draft, ...updates } : draft)));
  const removeAgent = (id: string) => setAgentDrafts((current) => current.filter((draft) => draft.id !== id));

  const restoreScenarioDraft = () => {
    if (!analyzedBackgroundDraft.trim()) return;
    setBackgroundDraft(analyzedBackgroundDraft);
  };
  const restoreSettingsDrafts = () => setSettingsDrafts(extractedSettingsDrafts.map(cloneSettingDraft));
  const restoreActionDrafts = () => setActionDrafts(extractedActionDrafts.map((draft) => cloneDraftItem(draft, 'action')));
  const restoreAgentDrafts = () => setAgentDrafts(extractedAgentDrafts.map((draft) => cloneDraftItem(draft, 'agent')));
  const restoreVariableDrafts = () => setVariableDrafts(extractedVariableValues.map((value) => ({ id: createId('variable'), value })));

  const mergeFieldEvidence = (field: AiScientistReextractField, evidenceItems: string[]) => {
    if (evidenceItems.length === 0) return;
    setEvidenceByField((current) => {
      const next = { ...current };
      const mapping: Record<AiScientistReextractField, string[]> = {
        scenario: ['research_goal', 'setting', 'decision_context'],
        settings: ['payoff_rules', 'constraints', 'information_structure', 'interaction_topology', 'interaction_structure'],
        actions: ['actions'],
        agents: ['participants'],
        variables: ['key_variables'],
      };
      for (const key of mapping[field]) {
        next[key] = evidenceItems;
      }
      return next;
    });
  };

  const handleReextractField = async (field: AiScientistReextractField) => {
    const trimmed = researchText.trim();
    if (!trimmed) return;
    setRepairingField(field);
    setErrorMessage('');
    try {
      const refreshed = await reextractAiScientistField({
        text: trimmed,
        field,
        language: i18n.language,
        sourceSections,
      });
      mergeFieldEvidence(field, refreshed.evidence || []);
      if (field === 'scenario') {
        const nextValue = (refreshed.scenario_description || '').trim();
        setAnalyzedBackgroundDraft(nextValue);
        if (nextValue) setBackgroundDraft(nextValue);
      } else if (field === 'settings') {
        const nextDrafts = (refreshed.settings || []).map(makeSettingDraft);
        setExtractedSettingsDrafts(nextDrafts);
        setSettingsDrafts(nextDrafts.map(cloneSettingDraft));
      } else if (field === 'actions') {
        const nextDrafts = (refreshed.actions || []).map(makeActionDraft);
        setExtractedActionDrafts(nextDrafts);
        setActionDrafts(nextDrafts.map((draft) => cloneDraftItem(draft, 'action')));
      } else if (field === 'agents') {
        const nextDrafts = (refreshed.agents || []).map(makeAgentDraft);
        setExtractedAgentDrafts(nextDrafts);
        setAgentDrafts(nextDrafts.map((draft) => cloneDraftItem(draft, 'agent')));
      } else if (field === 'variables') {
        const nextValues = (refreshed.key_variables || []).filter((item) => item.trim().length > 0);
        setExtractedVariableValues(nextValues);
        setVariableDrafts(nextValues.map((value) => ({ id: createId('variable'), value })));
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t('createExperiment.customBuilder.reextractFailed', { defaultValue: 'Failed to re-extract this field.' }));
    } finally {
      setRepairingField(null);
    }
  };

  const addSuggestedVariable = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    setVariableDrafts((current) => {
      if (current.some((draft) => normalizeToken(draft.value) === normalizeToken(trimmed))) return current;
      return [...current, { id: createId('variable'), value: trimmed }];
    });
  };

  const addSuggestedAction = (action: AiScientistAction) => {
    const label = action.name.trim();
    if (!label) return;
    setActionDrafts((current) => {
      if (current.some((draft) => normalizeToken(draft.label) === normalizeToken(label))) return current;
      return [...current, makeActionDraft(action)];
    });
  };

  const addSuggestedAgent = (agent: AiScientistAgent) => {
    const label = agent.label.trim();
    if (!label) return;
    setAgentDrafts((current) => {
      if (current.some((draft) => normalizeToken(draft.label) === normalizeToken(label))) return current;
      return [...current, makeAgentDraft(agent)];
    });
  };

  const addSuggestedSetting = (setting: AiScientistSetting) => {
    const key = setting.key.trim();
    if (!key) return;
    setSettingsDrafts((current) => {
      const matchIndex = current.findIndex((draft) => normalizeToken(draft.key) === normalizeToken(key));
      if (matchIndex === -1) return [...current, makeSettingDraft(setting)];
      const next = [...current];
      next[matchIndex] = {
        ...next[matchIndex],
        value: next[matchIndex].value || setting.value,
        reason: next[matchIndex].reason || setting.reason,
      };
      return next;
    });
  };

  const applyBuilderState = async () => {
    const scenarioDescription = backgroundDraft.trim() || researchText.trim();
    const finalScenarioName = scenarioName.trim() || deriveScenarioName(t, {
      scenario_description: scenarioDescription,
      semantic_schema: semanticSchema || undefined,
      template_suggestions: templateOptions,
      recommended_scenario_id: recommendedScenarioId,
    }, sourceFileName);
    const approvedActions = buildActionsForStore(selectedActionDrafts.length > 0 ? selectedActionDrafts : actionDrafts);
    const approvedAgents = buildAgentsForStore(selectedAgentDrafts.length > 0 ? selectedAgentDrafts : agentDrafts);

    if (!scenarioDescription || approvedActions.length === 0 || approvedAgents.length === 0) {
      setErrorMessage(t('createExperiment.customBuilder.reviewBeforeContinue', { defaultValue: 'Review the scenario, actions, and agents before continuing.' }));
      return;
    }

    const scenarioParams = buildScenarioParams(
      settingsDrafts,
      variableDrafts,
      assumptions,
      missingInformation,
      evidence,
      sourceSections,
      semanticSchema,
      sourceFileName,
      researchText,
      recommendedParams,
    );
    scenarioParams.ai_scientist_template_name = finalScenarioName;
    scenarioParams.ai_scientist_save_template = saveAsPresetTemplate;

    setIsApplying(true);
    setErrorMessage('');

    try {
      reset();

      const chosenTemplateId = selectedTemplateId || (recommendedScenarioId !== 'custom' ? recommendedScenarioId : null);

      if (builderMode === 'recommended' && chosenTemplateId) {
        const recommendedScenario = await getScenario(chosenTemplateId);
        const defaults = Object.fromEntries(
          (recommendedScenario.parameters || []).map((param) => [param.key, param.default]),
        );
        const {
          availableActions: recommendedRuntimeActions,
          selectedActionIds: recommendedSelectedActionIds,
        } = resolveRecommendedScenarioActions(recommendedScenario, approvedActions);
        const mergedParams = {
          ...defaults,
          ...scenarioParams,
        };

        setSelectedScenarioId(recommendedScenario.id);
        setSelectedScenarioData({
          ...recommendedScenario,
          name: finalScenarioName,
        });
        setScenarioDescription(scenarioDescription);
        setScenarioParams(mergedParams);
        setAvailableActions(recommendedRuntimeActions);
        setSelectedActionIds(recommendedSelectedActionIds);
        setAgentMode('manual');
        approvedAgents.forEach((agent) => addAgentType(agent));
        setSocialNetwork({});
        markStepComplete(1);
        setCurrentStep(2);
      } else {
        const customRuntimeActions = approvedActions.length > 0 ? approvedActions : CUSTOM_RUNTIME_ACTIONS;

        setSelectedScenarioId('custom');
        setSelectedScenarioData({
          id: 'custom',
          name: finalScenarioName,
          category: 'custom',
          description: scenarioDescription,
          interaction_mode: 'sequential',
          display_type: 'params',
          parameters: [],
          actions: customRuntimeActions,
          category_actions: customRuntimeActions,
          default_action_ids: customRuntimeActions.map((item) => item.name),
        });
        setScenarioDescription(scenarioDescription);
        setScenarioParams({
          ...scenarioParams,
          custom_prompt: scenarioDescription,
          turn_ordering: 'sequential',
        });
        setAvailableActions(customRuntimeActions);
        setSelectedActionIds(customRuntimeActions.map((item) => item.name));
        setAgentMode('manual');
        approvedAgents.forEach((agent) => addAgentType(agent));
        setRoundVisibility('sequential');
        setTurnOrder('fixed');
        setSocialNetwork({});
        markStepComplete(1);
        setCurrentStep(2);
      }

      navigate('/simulations/create/preset', {
        state: {
          preserveBuilderState: true,
          startStep: 2,
          sourceFlow: 'research-custom',
        },
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t('createExperiment.customBuilder.applyFailed', { defaultValue: 'Failed to apply the generated draft.' }));
    } finally {
      setIsApplying(false);
    }
  };

  const templateOptions = useMemo(() => {
    if (templateSuggestions.length > 0) return templateSuggestions;
    if (!suggestedTemplate) return [];
    return [suggestedTemplate];
  }, [suggestedTemplate, templateSuggestions]);

  const rankedPresetOptions = useMemo(() => {
    const recommendationMap = new Map(templateOptions.map((item) => [item.id, item]));
    const builtinScenarios = allScenarios.filter((scenario) => scenario.id !== 'custom' && scenario.category !== 'custom');

    const mapped = builtinScenarios.map((scenario) => {
      const recommended = recommendationMap.get(scenario.id);
      return {
        id: scenario.id,
        name: scenario.name,
        category: scenario.category,
        description: scenario.description,
        score: recommended?.score ?? 0,
        reason: recommended?.reason ?? t('createExperiment.customBuilder.templateGenericReason', {
          defaultValue: 'Use this preset if you want to map the current draft into an existing built-in scenario structure.',
        }),
      };
    });

    return mapped.sort((left, right) => {
      if (right.score !== left.score) return right.score - left.score;
      return left.name.localeCompare(right.name);
    });
  }, [allScenarios, t, templateOptions]);

  const selectedTemplate = useMemo(() => {
    if (!rankedPresetOptions.length) return null;
    return rankedPresetOptions.find((item) => item.id === selectedTemplateId)
      || suggestedTemplateForScenario(rankedPresetOptions, recommendedScenarioId);
  }, [rankedPresetOptions, recommendedScenarioId, selectedTemplateId]);
  const primaryPresetOption = useMemo(() => selectedTemplate || rankedPresetOptions[0] || null, [rankedPresetOptions, selectedTemplate]);
  const alternativePresetOptions = useMemo(
    () => rankedPresetOptions.filter((item) => item.id !== primaryPresetOption?.id),
    [primaryPresetOption, rankedPresetOptions],
  );

  const semanticSchemaSections = useMemo(() => {
    if (!semanticSchema) return [];
    return [
      {
        key: 'research-goal',
        title: t('createExperiment.customBuilder.schemaResearchGoal', { defaultValue: 'Research Goal' }),
        content: semanticSchema.research_goal ? [semanticSchema.research_goal] : [],
      },
      {
        key: 'setting',
        title: t('createExperiment.customBuilder.schemaSetting', { defaultValue: 'Setting / Environment' }),
        content: semanticSchema.setting ? [semanticSchema.setting] : [],
      },
      {
        key: 'participants',
        title: t('createExperiment.customBuilder.schemaParticipants', { defaultValue: 'Participants / Agent Roles' }),
        content: (semanticSchema.participants || []).map((participant) => {
          const countLabel = participant.count > 1 ? ` × ${participant.count}` : '';
          return `${participant.label}${countLabel}${participant.description ? `: ${participant.description}` : ''}`;
        }),
      },
      {
        key: 'decision-context',
        title: t('createExperiment.customBuilder.schemaDecisionContext', { defaultValue: 'Decision Context' }),
        content: semanticSchema.decision_context || [],
      },
      {
        key: 'choices',
        title: t('createExperiment.customBuilder.schemaChoices', { defaultValue: 'Per-round Choices' }),
        content: (semanticSchema.choices || []).map((choice) => `${choice.name}${choice.description ? `: ${choice.description}` : ''}`),
      },
      {
        key: 'payoff-rules',
        title: t('createExperiment.customBuilder.schemaPayoffRules', { defaultValue: 'Payoff / Feedback Rules' }),
        content: semanticSchema.payoff_rules || [],
      },
      {
        key: 'constraints',
        title: t('createExperiment.customBuilder.schemaConstraints', { defaultValue: 'Constraints / Termination' }),
        content: semanticSchema.constraints || [],
      },
      {
        key: 'information-structure',
        title: t('createExperiment.customBuilder.schemaInformationStructure', { defaultValue: 'Information Structure' }),
        content: semanticSchema.information_structure || [],
      },
      {
        key: 'interaction-topology',
        title: t('createExperiment.customBuilder.schemaInteractionTopology', { defaultValue: 'Interaction Topology' }),
        content: semanticSchema.interaction_topology || [],
      },
      {
        key: 'interaction-structure',
        title: t('createExperiment.customBuilder.schemaInteractionStructure', { defaultValue: 'Interaction Structure' }),
        content: semanticSchema.interaction_structure?.type && semanticSchema.interaction_structure.type !== 'generic'
          ? [semanticSchema.interaction_structure.display_label || semanticSchema.interaction_structure.type.replace(/_/g, ' ')]
          : [],
      },
      {
        key: 'interventions',
        title: t('createExperiment.customBuilder.schemaInterventions', { defaultValue: 'Interventions / Treatments' }),
        content: semanticSchema.interventions || [],
      },
      {
        key: 'outcomes',
        title: t('createExperiment.customBuilder.schemaOutcomes', { defaultValue: 'Observed Outcomes' }),
        content: semanticSchema.outcomes || [],
      },
      {
        key: 'key-variables',
        title: t('createExperiment.customBuilder.schemaKeyVariables', { defaultValue: 'Key Variables' }),
        content: semanticSchema.key_variables || [],
      },
    ].filter((section) => section.content.length > 0);
  }, [semanticSchema, t]);

  const fieldEvidence = useMemo(() => {
      const evidenceMap = Object.keys(evidenceByField || {}).length > 0 ? evidenceByField : (semanticSchema?.evidence_map || {});
    const filterByLabel = (needle: string) =>
      evidence
        .filter((item) => item.label.toLowerCase().includes(needle))
        .map((item) => item.snippet);

    return {
      scenario: dedupeStrings([
        ...(evidenceMap.research_goal || []),
        ...(evidenceMap.decision_context || []),
        semanticSchema?.research_goal,
        semanticSchema?.setting,
      ]),
      settings: dedupeStrings([
        ...(evidenceMap.payoff_rules || []),
        ...(evidenceMap.constraints || []),
        ...(evidenceMap.information_structure || []),
        ...(semanticSchema?.interaction_topology || []),
        ...(semanticSchema?.outcomes || []),
      ]),
      actions: dedupeStrings([
        ...filterByLabel('action:'),
        ...filterByLabel('动作：'),
        ...(semanticSchema?.decision_context || []),
      ]),
      agents: dedupeStrings([
        ...(semanticSchema?.participants || []).map((participant) => `${participant.label}${participant.description ? `: ${participant.description}` : ''}`),
        ...(semanticSchema?.decision_context || []),
      ]),
      variables: dedupeStrings([
        ...filterByLabel('variable:'),
        ...filterByLabel('变量：'),
        ...(semanticSchema?.key_variables || []),
      ]),
    };
  }, [evidence, evidenceByField, semanticSchema]);

  const schemaSettingSuggestions = useMemo(() => {
    if (!semanticSchema) return [];
    const suggestions: AiScientistSetting[] = [];
    if (semanticSchema.research_goal) {
      suggestions.push({
        key: 'research_question',
        value: semanticSchema.research_goal,
        reason: t('createExperiment.customBuilder.settingReasonResearchGoal', { defaultValue: 'Recovered from the source research goal.' }),
      });
    }
    if (semanticSchema.setting) {
      suggestions.push({
        key: 'environment_summary',
        value: semanticSchema.setting,
        reason: t('createExperiment.customBuilder.settingReasonSetting', { defaultValue: 'Recovered from the environment or setup description.' }),
      });
    }
    if (semanticSchema.payoff_rules?.length) {
      suggestions.push({
        key: 'payoff_rules',
        value: semanticSchema.payoff_rules.slice(0, 2).join(' '),
        reason: t('createExperiment.customBuilder.settingReasonPayoff', { defaultValue: 'Recovered from the payoff and feedback rules.' }),
      });
    }
    if (semanticSchema.constraints?.length) {
      suggestions.push({
        key: 'constraints',
        value: semanticSchema.constraints.slice(0, 2).join(' '),
        reason: t('createExperiment.customBuilder.settingReasonConstraints', { defaultValue: 'Recovered from the source constraints or termination conditions.' }),
      });
    }
    if (semanticSchema.information_structure?.length) {
      suggestions.push({
        key: 'information_structure',
        value: semanticSchema.information_structure.slice(0, 2).join(' '),
        reason: t('createExperiment.customBuilder.settingReasonInfo', { defaultValue: 'Recovered from the information visibility described in the source.' }),
      });
    }
    if (semanticSchema.interaction_topology?.length) {
      suggestions.push({
        key: 'interaction_topology',
        value: semanticSchema.interaction_topology.slice(0, 2).join(' '),
        reason: t('createExperiment.customBuilder.settingReasonTopology', { defaultValue: 'Recovered from the source interaction topology.' }),
      });
    }
    if (semanticSchema.interaction_structure?.type && semanticSchema.interaction_structure.type !== 'generic') {
      suggestions.push({
        key: 'interaction_structure',
        value: semanticSchema.interaction_structure.display_label || semanticSchema.interaction_structure.type,
        reason: t('createExperiment.customBuilder.settingReasonStructure', { defaultValue: 'Recovered from the inferred interaction structure.' }),
      });
    }
    return suggestions;
  }, [semanticSchema, t]);

  return (
    <div className="studio-page px-6 py-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-[var(--ss-accent-warm-soft)] p-3 text-[var(--ss-brand-primary)]">
                <BrainCircuit size={24} />
              </div>
              <div>
                <h1 className="text-3xl font-semibold tracking-tight" style={{ color: 'var(--ss-heading)' }}>
                  {t('createExperiment.customBuilder.title', { defaultValue: 'Create Experiment from Research' })}
                </h1>
                <p className="max-w-3xl text-base leading-7" style={{ color: 'var(--ss-text)' }}>
                  {t('createExperiment.customBuilder.subtitle', { defaultValue: 'Paste source text or upload a paper, reconstruct the experiment draft, then hand it back to the standard builder for parameter, agent, and network confirmation.' })}
                </p>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            <Button variant="outline" onClick={() => navigate('/simulations/create')}>
              {t('common.back', { defaultValue: 'Back' })}
            </Button>
            <Button variant="outline" onClick={clearDraft} disabled={isAnalyzing || isUploading || isApplying}>
              {t('createExperiment.customBuilder.clearDraft', { defaultValue: 'Clear Draft' })}
            </Button>
          </div>
        </div>

        <Card className="p-5">
          <div className="space-y-4">
            <div>
              <h2 className="text-lg font-semibold" style={{ color: 'var(--ss-heading)' }}>
                {t('createExperiment.customBuilder.recognitionModeTitle', { defaultValue: 'Recognition Mode' })}
              </h2>
              <p className="mt-1 text-sm" style={{ color: 'var(--ss-text)' }}>
                {t('createExperiment.customBuilder.recognitionModeHint', { defaultValue: 'Choose whether to use deterministic backend recognition or a configured provider model before analyzing the source.' })}
              </p>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <button
                type="button"
                onClick={() => setRecognitionMode('provider')}
                className="rounded-2xl border p-4 text-left transition"
                style={{
                  borderColor: recognitionMode === 'provider' ? 'var(--ss-brand-primary)' : 'var(--ss-border-strong)',
                  background: recognitionMode === 'provider' ? 'var(--ss-accent-warm-soft)' : 'var(--ss-page-surface)',
                }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                      {t('createExperiment.customBuilder.modeProviderTitle', { defaultValue: '接入 Provider 智能识别' })}
                    </div>
                    <p className="mt-2 text-sm leading-6" style={{ color: 'var(--ss-text)' }}>
                      {t('createExperiment.customBuilder.modeProviderBody', { defaultValue: '调用你已配置的模型完成实验理解、模板推荐和草案生成。识别能力会明显受到模型强弱影响，强模型效果最好，但会消耗对应 token 或本地推理资源。' })}
                    </p>
                  </div>
                  {recognitionMode === 'provider' ? <Sparkles size={18} style={{ color: 'var(--ss-brand-primary)' }} /> : null}
                </div>
              </button>

              <button
                type="button"
                onClick={() => setRecognitionMode('deterministic')}
                className="rounded-2xl border p-4 text-left transition"
                style={{
                  borderColor: recognitionMode === 'deterministic' ? 'var(--ss-brand-primary)' : 'var(--ss-border-strong)',
                  background: recognitionMode === 'deterministic' ? 'var(--ss-accent-warm-soft)' : 'var(--ss-page-surface)',
                }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                      {t('createExperiment.customBuilder.modeDeterministicTitle', { defaultValue: '本地识别模式' })}
                    </div>
                    <p className="mt-2 text-sm leading-6" style={{ color: 'var(--ss-text)' }}>
                      {t('createExperiment.customBuilder.modeDeterministicBody', { defaultValue: '主要靠后端预处理、规则抽取和模板匹配完成识别，完全不依赖 provider。适合本地小模型能力偏弱、希望不消耗 token 先得到可编辑草案的用户，但复杂论文的识别能力会更有限。' })}
                    </p>
                  </div>
                  {recognitionMode === 'deterministic' ? <Check size={18} style={{ color: 'var(--ss-brand-primary)' }} /> : null}
                </div>
              </button>
            </div>

            <div className="rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                    {t('createExperiment.customBuilder.modeCurrentLabel', { defaultValue: '当前模式' })}
                  </div>
                  <p className="mt-1 text-sm leading-6" style={{ color: 'var(--ss-text)' }}>
                    {modeSummary}
                  </p>
                </div>

                {recognitionMode === 'provider' ? (
                  <div className="min-w-[260px] max-w-full">
                    <label className="mb-2 block text-xs font-medium uppercase tracking-[0.08em]" style={{ color: 'var(--ss-text-muted)' }}>
                      {t('createExperiment.customBuilder.providerSelectLabel', { defaultValue: '识别模型' })}
                    </label>
                    <select
                      value={selectedProviderId ?? ''}
                      onChange={(event) => setSelectedProviderId(event.target.value ? Number(event.target.value) : null)}
                      className="w-full rounded-xl border px-3 py-2 text-sm outline-none"
                      style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
                    >
                      {configuredProviders.length === 0 ? (
                        <option value="">{t('createExperiment.customBuilder.providerMissing', { defaultValue: '暂无可用模型，请先到设置页完成 LLM 配置。' })}</option>
                      ) : null}
                      {configuredProviders.map((provider: Provider) => (
                        <option key={provider.id} value={provider.id}>
                          {provider.name} · {provider.model}{provider.is_default || provider.is_active ? ' · 默认' : ''}
                        </option>
                      ))}
                    </select>
                    {selectedProvider ? (
                      <div className="mt-2 text-xs" style={{ color: 'var(--ss-text-muted)' }}>
                        {selectedProvider.provider} · {selectedProvider.base_url || t('createExperiment.customBuilder.providerBuiltIn', { defaultValue: 'built-in endpoint' })}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </Card>

        {errorMessage && (
          <div className="rounded-2xl border px-4 py-3 text-sm" style={{ borderColor: 'var(--ss-danger)', background: 'var(--ss-danger-soft)', color: 'var(--ss-danger)' }}>
            {errorMessage}
          </div>
        )}

        <input
          data-testid="research-upload-input"
          ref={fileInputRef}
          type="file"
          accept=".txt,.pdf,.doc,.docx,text/plain,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          className="hidden"
          onChange={handleFileSelected}
        />

        <div className="space-y-6">
          <Card className="p-5">
            <div className="space-y-4">
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
                <div className="min-w-0">
                  <h2 className="text-lg font-semibold" style={{ color: 'var(--ss-heading)' }}>
                    {t('createExperiment.customBuilder.inputLabel', { defaultValue: 'Research Source' })}
                  </h2>
                  <p className="mt-1 text-sm" style={{ color: 'var(--ss-text)' }}>
                    {t('createExperiment.customBuilder.inputHint', { defaultValue: 'Paste an abstract, methods section, or upload a PDF/Word file. Image-based PDFs will be OCR’d automatically.' })}
                  </p>
                </div>
                <div className="flex flex-col gap-3 xl:items-end xl:justify-self-end">
                  <div className="flex flex-wrap justify-start gap-3 xl:justify-end">
                    <Button variant="outline" onClick={handleUploadClick} disabled={isAnalyzing || isUploading || isApplying}>
                      <Upload size={16} />
                      {isUploading ? t('common.loading', { defaultValue: 'Loading' }) : t('createExperiment.customBuilder.uploadFile', { defaultValue: 'Upload File' })}
                    </Button>
                    <Button data-testid="research-analyze-button" onClick={() => void runAnalysis(researchText)} disabled={isAnalyzing || isUploading || isApplying}>
                      {isAnalyzing ? t('common.loading', { defaultValue: 'Loading' }) : t('createExperiment.customBuilder.analyze', { defaultValue: 'Analyze' })}
                    </Button>
                    <button
                      type="button"
                      data-testid="research-save-template-toggle"
                      onClick={() => setSaveAsPresetTemplate((current) => !current)}
                      disabled={isAnalyzing || isUploading || isApplying}
                      className="inline-flex items-center gap-3 rounded-2xl border px-3 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-60"
                      style={{
                        borderColor: saveAsPresetTemplate ? 'var(--ss-brand-primary)' : 'var(--ss-border-strong)',
                        background: saveAsPresetTemplate ? 'var(--ss-brand-soft)' : 'var(--ss-page-surface)',
                        color: 'var(--ss-text)',
                      }}
                      aria-pressed={saveAsPresetTemplate}
                    >
                      <span
                        className="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
                        style={{ background: saveAsPresetTemplate ? 'var(--ss-brand-primary)' : 'var(--ss-border-strong)' }}
                      >
                        <span
                          className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${saveAsPresetTemplate ? 'translate-x-6' : 'translate-x-1'}`}
                        />
                      </span>
                      <span className="text-left">
                        {t('createExperiment.customBuilder.saveTemplateToggle', { defaultValue: '创建后保存到我的预设模板' })}
                      </span>
                    </button>
                  </div>
                  {sourceAsset ? (
                    <div className="flex flex-wrap justify-start gap-2 xl:justify-end">
                      <div
                        data-testid="research-extraction-summary"
                        className="inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs"
                        style={{ borderColor: 'var(--ss-border-strong)', color: 'var(--ss-text-muted)' }}
                      >
                        <FileSearch size={14} />
                        <span>{localizedExtractionMethod(sourceAsset.extraction_method || 'uploaded', t)}</span>
                        {sourceAsset.page_count ? (
                          <span>{t('createExperiment.customBuilder.pageCount', { defaultValue: '{{count}} pages', count: sourceAsset.page_count })}</span>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>

              <textarea
                data-testid="research-source-text"
                value={researchText}
                onChange={(event) => setResearchText(event.target.value)}
                rows={14}
                className="w-full rounded-2xl border px-4 py-3 text-sm outline-none"
                style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
                placeholder={t('createExperiment.customBuilder.inputPlaceholder', { defaultValue: 'Paste the paper abstract, methods section, or research prompt here.' })}
              />

              {sourceFileName && (
                <div data-testid="research-source-file-card" className="rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium" style={{ color: 'var(--ss-heading)' }}>
                        {t('createExperiment.customBuilder.sourceFileLabel', { defaultValue: 'Source file' })}
                      </div>
                      <p className="mt-1 text-sm" style={{ color: 'var(--ss-text)' }}>{sourceFileName}</p>
                    </div>
                    <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--ss-text-muted)' }}>
                      <ScanSearch size={14} />
                      <span>{localizedExtractionMethod(sourceAsset?.extraction_method || 'uploaded', t)}</span>
                    </div>
                  </div>
                  {sourceDiagnostics.length > 0 && (
                    <div className="mt-3 rounded-xl border px-3 py-2 text-sm" style={{ borderColor: 'var(--ss-warning)', background: 'var(--ss-brand-soft)', color: 'var(--ss-text)' }}>
                      {sourceDiagnostics.join(' ')}
                    </div>
                  )}
                </div>
              )}
            </div>
          </Card>

          <Card className="p-5">
            <div className="space-y-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold" style={{ color: 'var(--ss-heading)' }}>
                    {t('createExperiment.customBuilder.builderPathMergedTitle', { defaultValue: 'Choose how to continue building this experiment' })}
                  </h2>
                  <p className="mt-1 text-sm" style={{ color: 'var(--ss-text)' }}>
                    {t('createExperiment.customBuilder.reviewSubtitle', { defaultValue: 'These are extracted draft results. Please manually review, edit, and choose how you want to continue before they are written into the standard builder.' })}
                  </p>
                </div>
                <div className="rounded-xl border px-3 py-2 text-xs" style={{ borderColor: 'var(--ss-border-strong)', color: 'var(--ss-text-muted)' }}>
                  {t('createExperiment.customBuilder.confidenceLabel', {
                    defaultValue: 'Confidence: {{score}}%',
                    score: Math.round((recommendationConfidence || 0) * 100),
                  })}
                </div>
              </div>

              <div className="grid gap-3 xl:grid-cols-2">
                <button
                  data-testid="builder-mode-custom"
                  type="button"
                  onClick={() => setBuilderMode('custom')}
                  aria-pressed={builderMode === 'custom'}
                  className="rounded-2xl border p-4 text-left transition"
                  style={{
                    borderColor: builderMode === 'custom' ? 'var(--ss-brand-primary)' : 'var(--ss-border-strong)',
                    background: builderMode === 'custom' ? 'var(--ss-brand-soft)' : 'var(--ss-page-surface)',
                  }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-base font-semibold" style={{ color: 'var(--ss-heading)' }}>
                        {t('createExperiment.customBuilder.useCustomTitle', { defaultValue: 'Stay in custom scenario mode' })}
                      </div>
                      <p className="mt-2 text-sm leading-6" style={{ color: 'var(--ss-text)' }}>
                        {t('createExperiment.customBuilder.useCustomDescription', { defaultValue: 'Use the reconstructed scene and custom action set directly, then continue through the standard builder from Step 2.' })}
                      </p>
                    </div>
                    {builderMode === 'custom' ? <Check size={18} style={{ color: 'var(--ss-brand-primary)' }} /> : null}
                  </div>
                </button>

                <div
                  data-testid="builder-mode-recommended"
                  className="rounded-2xl border p-4"
                  style={{
                    borderColor: builderMode === 'recommended' ? 'var(--ss-brand-primary)' : 'var(--ss-border-strong)',
                    background: builderMode === 'recommended' ? 'var(--ss-brand-soft)' : 'var(--ss-page-surface)',
                  }}
                >
                  <button
                    type="button"
                    onClick={() => setBuilderMode('recommended')}
                    aria-pressed={builderMode === 'recommended'}
                    className="w-full text-left"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-base font-semibold" style={{ color: 'var(--ss-heading)' }}>
                          {t('createExperiment.customBuilder.useRecommendedTitle', { defaultValue: 'Map into a preset scenario' })}
                        </div>
                        <p className="mt-2 text-sm leading-6" style={{ color: 'var(--ss-text)' }}>
                          {primaryPresetOption
                            ? t('createExperiment.customBuilder.reviewRecommended', {
                              defaultValue: 'The system found a plausible mapping, but you should review the candidate templates before continuing.',
                            })
                            : t('createExperiment.customBuilder.useRecommendedDisabled', { defaultValue: 'No strong preset match was found for this source.' })}
                        </p>
                      </div>
                      {builderMode === 'recommended' ? <Check size={18} style={{ color: 'var(--ss-brand-primary)' }} /> : null}
                    </div>
                  </button>

                  {primaryPresetOption ? (
                    <div className="mt-4 rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)' }}>
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--ss-text-muted)' }}>
                            {t('createExperiment.customBuilder.modeRecommended', { defaultValue: 'Preset-assisted path' })}
                          </div>
                          <div className="mt-1 text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                            {primaryPresetOption.name}
                          </div>
                          <div className="mt-1 text-xs" style={{ color: 'var(--ss-text-muted)' }}>
                            {primaryPresetOption.category}
                          </div>
                        </div>
                        <div className="rounded-full border px-3 py-1 text-xs font-medium" style={{ borderColor: 'var(--ss-border-strong)', color: 'var(--ss-text)' }}>
                          {Math.round(primaryPresetOption.score * 100)}%
                        </div>
                      </div>
                    </div>
                  ) : null}

                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    {reviewRequired && primaryPresetOption ? (
                      <div className="rounded-full border px-3 py-1 text-xs" style={{ borderColor: 'var(--ss-warning)', color: 'var(--ss-text)' }}>
                        {t('createExperiment.customBuilder.reviewRecommended', {
                          defaultValue: 'The system found a plausible mapping, but you should review the candidate templates before continuing.',
                        })}
                      </div>
                    ) : null}
                    {(primaryPresetOption || alternativePresetOptions.length > 0 || Object.keys(recommendedParams).length > 0) ? (
                      <button
                        type="button"
                        onClick={() => setShowRecommendedTemplateDetails((current) => !current)}
                        className="inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm transition"
                        style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)', color: 'var(--ss-text)' }}
                      >
                        <span>
                          {showRecommendedTemplateDetails
                            ? t('createExperiment.customBuilder.hideAllTemplates', { defaultValue: 'Hide remaining built-in presets' })
                            : t('createExperiment.customBuilder.showAllTemplates', { defaultValue: 'Show all built-in preset templates' })}
                        </span>
                        <ChevronDown
                          size={16}
                          className={`transition-transform ${showRecommendedTemplateDetails ? 'rotate-180' : ''}`}
                        />
                      </button>
                    ) : null}
                  </div>

                  {showRecommendedTemplateDetails ? (
                    <div className="mt-4 space-y-4 rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)' }}>
                      {recommendedScenarioReason ? (
                        <div className="text-sm leading-6" style={{ color: 'var(--ss-text)' }}>
                          {recommendedScenarioReason}
                        </div>
                      ) : null}

                      {alternativePresetOptions.length > 0 ? (
                        <div className="grid gap-3 md:grid-cols-2">
                          {alternativePresetOptions.map((option) => {
                            const isSelected = selectedTemplate?.id === option.id;
                            return (
                              <button
                                key={option.id}
                                type="button"
                                onClick={() => {
                                  setSelectedTemplateId(option.id);
                                  setBuilderMode('recommended');
                                }}
                                className="w-full rounded-2xl border p-4 text-left transition"
                                style={{
                                  borderColor: isSelected ? 'var(--ss-brand-primary)' : 'var(--ss-border-strong)',
                                  background: isSelected ? 'var(--ss-brand-soft)' : 'var(--ss-page-surface)',
                                }}
                              >
                                <div className="flex items-start justify-between gap-3">
                                  <div>
                                    <div className="font-semibold" style={{ color: 'var(--ss-heading)' }}>
                                      {option.name}
                                    </div>
                                    <div className="mt-1 text-xs uppercase tracking-wide" style={{ color: 'var(--ss-text-muted)' }}>
                                      {option.category} · {Math.round(option.score * 100)}%
                                    </div>
                                  </div>
                                  {isSelected ? <Check size={16} /> : null}
                                </div>
                                <div className="mt-2 text-sm leading-6" style={{ color: 'var(--ss-text)' }}>
                                  {option.reason}
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      ) : null}

                      {Object.keys(recommendedParams).length > 0 ? (
                        <div className="rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
                          <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                            {t('createExperiment.customBuilder.prefillParamsTitle', { defaultValue: 'Detected parameter hints' })}
                          </div>
                          <div className="mt-3 space-y-2">
                            {Object.entries(recommendedParams).map(([key, value]) => (
                              <div key={key} className="flex items-start justify-between gap-3 text-sm">
                                <div style={{ color: 'var(--ss-text-muted)' }}>{key}</div>
                                <div className="text-right" style={{ color: 'var(--ss-text)' }}>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          </Card>

          <Card className="p-5">
            <div className="space-y-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold" style={{ color: 'var(--ss-heading)' }}>
                    {t('createExperiment.customBuilder.reviewTitle', { defaultValue: 'Review before continuing' })}
                  </h2>
                  <p className="mt-1 text-sm" style={{ color: 'var(--ss-text)' }}>
                    {t('createExperiment.customBuilder.reviewSubtitle', { defaultValue: 'These are extracted draft results. Please manually review, edit, and choose how you want to continue before they are written into the standard builder.' })}
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                  <label className="text-sm font-medium" style={{ color: 'var(--ss-heading)' }}>
                    {t('createExperiment.customBuilder.templateNameLabel', { defaultValue: 'Experiment scene name' })}
                  </label>
                  <input
                    data-testid="research-scenario-name"
                    value={scenarioName}
                    onChange={(event) => setScenarioName(event.target.value)}
                    className="w-full rounded-2xl border px-4 py-3 text-sm outline-none"
                    style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
                    placeholder={t('createExperiment.customBuilder.templateNamePlaceholder', { defaultValue: 'Name this experiment scene' })}
                  />
                  <p className="text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
                    {t('createExperiment.customBuilder.templateNameHint', { defaultValue: 'This name will be used in the builder and, if enabled, when saving to your personal preset templates.' })}
                  </p>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium" style={{ color: 'var(--ss-heading)' }}>
                  {t('createExperiment.customBuilder.sceneTitle', { defaultValue: 'Scenario Draft' })}
                </label>
                <textarea
                  data-testid="research-background-draft"
                  value={backgroundDraft}
                  onChange={(event) => setBackgroundDraft(event.target.value)}
                  rows={10}
                  className="w-full rounded-2xl border px-4 py-3 text-sm outline-none"
                  style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
                  placeholder={t('createExperiment.customBuilder.scenePlaceholder', { defaultValue: 'Run analysis to generate a scenario description, then edit it here.' })}
                />
              </div>

              <div className="rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                  <Sparkles size={14} />
                  {t('createExperiment.customBuilder.variablesTitle', { defaultValue: 'Key Variables' })}
                </div>
                <div className="space-y-2">
                  {variableDrafts.length > 0 ? (
                    variableDrafts.map((draft) => (
                      <div key={draft.id} className="flex items-center gap-2">
                        <input
                          value={draft.value}
                          onChange={(event) => updateVariable(draft.id, event.target.value)}
                          className="min-w-0 flex-1 rounded-xl border px-3 py-2 text-sm outline-none"
                          style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
                          placeholder={t('createExperiment.customBuilder.variablePlaceholder', { defaultValue: 'Variable' })}
                        />
                        <Button variant="ghost" size="sm" onClick={() => removeVariable(draft.id)}>
                          {t('common.remove', { defaultValue: 'Remove' })}
                        </Button>
                      </div>
                    ))
                  ) : (
                    <p className="text-sm" style={{ color: 'var(--ss-text-muted)' }}>
                      {t('createExperiment.customBuilder.noVariables', { defaultValue: 'No key variables yet.' })}
                    </p>
                  )}
                </div>
                <div className="mt-3">
                  <Button variant="outline" size="sm" onClick={addVariable}>
                    <Check size={14} />
                    {t('createExperiment.customBuilder.addVariable', { defaultValue: 'Add Variable' })}
                  </Button>
                </div>
              </div>

            </div>
          </Card>

          <ActionsDraftPanel
            t={t}
            textColor="var(--ss-heading)"
            helperText={t('createExperiment.customBuilder.actionsHelperText', {
              defaultValue: 'Keep only the decisions that really belong in each interaction round. You can restore the analyzed action set anytime.',
            })}
            headerAction={(
              <Button variant="outline" size="sm" onClick={restoreActionDrafts} disabled={extractedActionDrafts.length === 0}>
                <RotateCcw size={14} />
                {t('createExperiment.customBuilder.restoreField', { defaultValue: 'Restore extracted' })}
              </Button>
            )}
            actionDrafts={actionDrafts}
            onAddAction={addAction}
            onUpdateAction={updateAction}
            onRemoveAction={removeAction}
          />

          <AgentsDraftPanel
            t={t}
            textColor="var(--ss-heading)"
            helperText={t('createExperiment.customBuilder.agentsHelperText', {
              defaultValue: 'Named roles from the source should usually survive into the final experiment. Restore them here if the draft gets too generic.',
            })}
            headerAction={(
              <Button variant="outline" size="sm" onClick={restoreAgentDrafts} disabled={extractedAgentDrafts.length === 0}>
                <RotateCcw size={14} />
                {t('createExperiment.customBuilder.restoreField', { defaultValue: 'Restore extracted' })}
              </Button>
            )}
            agentDrafts={agentDrafts}
            onAddAgent={addAgent}
            onUpdateAgent={updateAgent}
            onRemoveAgent={removeAgent}
          />

          <CollapsibleCardSection
            title={t('createExperiment.customBuilder.advancedReviewTitle', { defaultValue: 'Advanced edits and review' })}
            hint={t('createExperiment.customBuilder.advancedReviewHint', {
              defaultValue: 'Open this area when you want to adjust extracted settings, repair individual fields, or inspect the underlying semantic structure and evidence.',
            })}
            defaultOpen={false}
          >
            <div className="space-y-4">
              <CollapsibleCardSection
                title={t('createExperiment.customBuilder.settingsTitle', { defaultValue: 'Draft scenario settings' })}
                hint={t('createExperiment.customBuilder.settingsCollapsedHint', {
                  defaultValue: 'These extracted settings are optional to review here. Open this section when you want to refine additional builder parameters.',
                })}
                defaultOpen={false}
              >
                <SettingsDraftPanel
                  t={t}
                  textColor="var(--ss-heading)"
                  helperText={t('createExperiment.customBuilder.settingsHelperText', {
                    defaultValue: 'These rows are editable builder parameters. Restore the extracted set if a manual edit wiped out too much.',
                  })}
                  headerAction={(
                    <Button variant="outline" size="sm" onClick={restoreSettingsDrafts} disabled={extractedSettingsDrafts.length === 0}>
                      <RotateCcw size={14} />
                      {t('createExperiment.customBuilder.restoreField', { defaultValue: 'Restore extracted' })}
                    </Button>
                  )}
                  settingsDrafts={settingsDrafts}
                  onAddSetting={addSetting}
                  onUpdateSetting={updateSetting}
                  onRemoveSetting={removeSetting}
                />
              </CollapsibleCardSection>

              <CollapsibleCardSection
                title={t('createExperiment.customBuilder.fieldRepairTitle', { defaultValue: 'Field-by-field repair' })}
                hint={t('createExperiment.customBuilder.fieldRepairHint', {
                  defaultValue: 'Review one field at a time. Restore the analyzed draft for a single field or pull back specific evidence-backed suggestions without resetting the whole page.',
                })}
                badge={(
                  <span className="rounded-xl border px-3 py-1.5 text-xs" style={{ borderColor: 'var(--ss-border-strong)', color: 'var(--ss-text-muted)' }}>
                    {t('createExperiment.customBuilder.fieldRepairBadge', { defaultValue: 'Evidence-backed edits' })}
                  </span>
                )}
                defaultOpen={false}
              >
                <div className="space-y-3">
                  <div className="rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                          {t('createExperiment.customBuilder.sceneTitle', { defaultValue: 'Scenario Draft' })}
                        </div>
                        <p className="mt-1 text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
                          {t('createExperiment.customBuilder.fieldRepairScenarioHint', { defaultValue: 'Use the extracted summary if your edited scenario drifted too far from the paper.' })}
                        </p>
                      </div>
                      <Button variant="outline" size="sm" onClick={restoreScenarioDraft} disabled={!analyzedBackgroundDraft.trim()}>
                        <RotateCcw size={14} />
                        {t('createExperiment.customBuilder.restoreField', { defaultValue: 'Restore extracted' })}
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => handleReextractField('scenario')} disabled={repairingField === 'scenario' || !researchText.trim()}>
                        {repairingField === 'scenario'
                          ? t('createExperiment.customBuilder.reextractingField', { defaultValue: 'Re-extracting…' })
                          : t('createExperiment.customBuilder.reextractField', { defaultValue: 'Re-extract field' })}
                      </Button>
                    </div>
                    {fieldEvidence.scenario.length > 0 ? (
                      <div className="mt-3 space-y-2">
                        {fieldEvidence.scenario.slice(0, 2).map((item, index) => (
                          <div key={`scenario-evidence-${index}`} className="rounded-xl border px-3 py-2 text-sm leading-6" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)', color: 'var(--ss-text)' }}>
                            <div className="mb-1 inline-flex items-center gap-2 text-xs" style={{ color: 'var(--ss-text-muted)' }}>
                              <Quote size={12} />
                              {t('createExperiment.customBuilder.evidenceSnippetLabel', { defaultValue: 'Evidence snippet' })}
                            </div>
                            {item}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  <div className="rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                          {t('createExperiment.customBuilder.settingsTitle')}
                        </div>
                        <p className="mt-1 text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
                          {t('createExperiment.customBuilder.fieldRepairSettingsHint', { defaultValue: 'Recover missing setup fields one row at a time instead of recreating the whole schema manually.' })}
                        </p>
                      </div>
                      <Button variant="outline" size="sm" onClick={restoreSettingsDrafts} disabled={extractedSettingsDrafts.length === 0}>
                        <RotateCcw size={14} />
                        {t('createExperiment.customBuilder.restoreField', { defaultValue: 'Restore extracted' })}
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => handleReextractField('settings')} disabled={repairingField === 'settings' || !researchText.trim()}>
                        {repairingField === 'settings'
                          ? t('createExperiment.customBuilder.reextractingField', { defaultValue: 'Re-extracting…' })
                          : t('createExperiment.customBuilder.reextractField', { defaultValue: 'Re-extract field' })}
                      </Button>
                    </div>
                    {schemaSettingSuggestions.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {schemaSettingSuggestions.map((item) => (
                          <button
                            key={`${item.key}-${item.value}`}
                            type="button"
                            onClick={() => addSuggestedSetting(item)}
                            className="rounded-full border px-3 py-1.5 text-xs transition"
                            style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-surface)', color: 'var(--ss-text)' }}
                          >
                            {item.key}
                          </button>
                        ))}
                      </div>
                    ) : null}
                    {fieldEvidence.settings.length > 0 ? (
                      <div className="mt-3 space-y-2">
                        {fieldEvidence.settings.slice(0, 2).map((item, index) => (
                          <div key={`settings-evidence-${index}`} className="rounded-xl border px-3 py-2 text-sm leading-6" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)', color: 'var(--ss-text)' }}>
                            {item}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  <div className="rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
                    <div className="grid gap-4 md:grid-cols-2">
                      <div>
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                              {t('createExperiment.customBuilder.actionsTitle')}
                            </div>
                            <p className="mt-1 text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
                              {t('createExperiment.customBuilder.fieldRepairActionsHint', { defaultValue: 'Bring back extracted decisions or add one missing action at a time.' })}
                            </p>
                          </div>
                          <Button variant="outline" size="sm" onClick={restoreActionDrafts} disabled={extractedActionDrafts.length === 0}>
                            <RotateCcw size={14} />
                            {t('createExperiment.customBuilder.restoreField', { defaultValue: 'Restore extracted' })}
                          </Button>
                          <Button variant="outline" size="sm" onClick={() => handleReextractField('actions')} disabled={repairingField === 'actions' || !researchText.trim()}>
                            {repairingField === 'actions'
                              ? t('createExperiment.customBuilder.reextractingField', { defaultValue: 'Re-extracting…' })
                              : t('createExperiment.customBuilder.reextractField', { defaultValue: 'Re-extract field' })}
                          </Button>
                        </div>
                        {(semanticSchema?.choices || []).length > 0 ? (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {(semanticSchema?.choices || []).map((choice) => (
                              <button
                                key={choice.name}
                                type="button"
                                onClick={() => addSuggestedAction(choice)}
                                className="rounded-full border px-3 py-1.5 text-xs transition"
                                style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-surface)', color: 'var(--ss-text)' }}
                              >
                                {choice.name}
                              </button>
                            ))}
                          </div>
                        ) : null}
                        {fieldEvidence.actions.length > 0 ? (
                          <div className="mt-3 space-y-2">
                            {fieldEvidence.actions.slice(0, 2).map((item, index) => (
                              <div key={`actions-evidence-${index}`} className="rounded-xl border px-3 py-2 text-sm leading-6" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)', color: 'var(--ss-text)' }}>
                                {item}
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>

                      <div>
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                              {t('createExperiment.customBuilder.agentsTitle')}
                            </div>
                            <p className="mt-1 text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
                              {t('createExperiment.customBuilder.fieldRepairAgentsHint', { defaultValue: 'Recover named roles from the source instead of retyping them if the draft got simplified.' })}
                            </p>
                          </div>
                          <Button variant="outline" size="sm" onClick={restoreAgentDrafts} disabled={extractedAgentDrafts.length === 0}>
                            <RotateCcw size={14} />
                            {t('createExperiment.customBuilder.restoreField', { defaultValue: 'Restore extracted' })}
                          </Button>
                          <Button variant="outline" size="sm" onClick={() => handleReextractField('agents')} disabled={repairingField === 'agents' || !researchText.trim()}>
                            {repairingField === 'agents'
                              ? t('createExperiment.customBuilder.reextractingField', { defaultValue: 'Re-extracting…' })
                              : t('createExperiment.customBuilder.reextractField', { defaultValue: 'Re-extract field' })}
                          </Button>
                        </div>
                        {(semanticSchema?.participants || []).length > 0 ? (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {(semanticSchema?.participants || []).map((participant) => (
                              <button
                                key={participant.label}
                                type="button"
                                onClick={() => addSuggestedAgent(participant)}
                                className="rounded-full border px-3 py-1.5 text-xs transition"
                                style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-surface)', color: 'var(--ss-text)' }}
                              >
                                {participant.label}
                              </button>
                            ))}
                          </div>
                        ) : null}
                        {fieldEvidence.agents.length > 0 ? (
                          <div className="mt-3 space-y-2">
                            {fieldEvidence.agents.slice(0, 2).map((item, index) => (
                              <div key={`agents-evidence-${index}`} className="rounded-xl border px-3 py-2 text-sm leading-6" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)', color: 'var(--ss-text)' }}>
                                {item}
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </div>

                  <div className="rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                          {t('createExperiment.customBuilder.variablesTitle', { defaultValue: 'Key Variables' })}
                        </div>
                        <p className="mt-1 text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
                          {t('createExperiment.customBuilder.fieldRepairVariablesHint', { defaultValue: 'Pull back important variables from the analysis when they disappear from the editable list.' })}
                        </p>
                      </div>
                      <Button variant="outline" size="sm" onClick={restoreVariableDrafts} disabled={extractedVariableValues.length === 0}>
                        <RotateCcw size={14} />
                        {t('createExperiment.customBuilder.restoreField', { defaultValue: 'Restore extracted' })}
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => handleReextractField('variables')} disabled={repairingField === 'variables' || !researchText.trim()}>
                        {repairingField === 'variables'
                          ? t('createExperiment.customBuilder.reextractingField', { defaultValue: 'Re-extracting…' })
                          : t('createExperiment.customBuilder.reextractField', { defaultValue: 'Re-extract field' })}
                      </Button>
                    </div>
                    {(semanticSchema?.key_variables || []).length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {(semanticSchema?.key_variables || []).map((item) => (
                          <button
                            key={item}
                            type="button"
                            onClick={() => addSuggestedVariable(item)}
                            className="rounded-full border px-3 py-1.5 text-xs transition"
                            style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-surface)', color: 'var(--ss-text)' }}
                          >
                            {item}
                          </button>
                        ))}
                      </div>
                    ) : null}
                    {fieldEvidence.variables.length > 0 ? (
                      <div className="mt-3 space-y-2">
                        {fieldEvidence.variables.slice(0, 2).map((item, index) => (
                          <div key={`variables-evidence-${index}`} className="rounded-xl border px-3 py-2 text-sm leading-6" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)', color: 'var(--ss-text)' }}>
                            {item}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              </CollapsibleCardSection>

              <CollapsibleCardSection
                title={t('createExperiment.customBuilder.semanticSchemaTitle', { defaultValue: 'Semantic Schema' })}
                hint={t('createExperiment.customBuilder.semanticSchemaHint', { defaultValue: 'This is the structured experiment skeleton the system inferred before generating the editable draft.' })}
                defaultOpen={false}
                testId="research-semantic-schema-section"
              >
                {hasSemanticSchemaContent(semanticSchema) ? (
                  <div data-testid="research-semantic-schema" className="grid gap-3 lg:grid-cols-2">
                    {semanticSchemaSections.map((section) => (
                      <div
                        key={section.key}
                        data-testid={`research-schema-${section.key}`}
                        className="rounded-2xl border p-4"
                        style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}
                      >
                        <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                          {section.title}
                        </div>
                        <div className="mt-2 space-y-2">
                          {section.content.map((item, index) => (
                            <p key={`${section.key}-${index}`} className="text-sm leading-6" style={{ color: 'var(--ss-text)' }}>
                              {item}
                            </p>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-2xl border border-dashed p-4 text-sm" style={{ borderColor: 'var(--ss-border-strong)', color: 'var(--ss-text-muted)' }}>
                    {t('createExperiment.customBuilder.noSemanticSchema', { defaultValue: 'Run analysis to see the extracted experiment schema here.' })}
                  </div>
                )}
              </CollapsibleCardSection>

              <CollapsibleCardSection
                title={t('createExperiment.customBuilder.validationNotesTitle', { defaultValue: 'Validation Notes' })}
                hint={t('createExperiment.customBuilder.validationNotesHint', { defaultValue: 'Open this section when you need to inspect why the current draft looks the way it does.' })}
                defaultOpen={false}
              >
                <div className="space-y-5">
              <div className="rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                  <AlertTriangle size={14} />
                  {t('createExperiment.customBuilder.reviewFlagsTitle', { defaultValue: 'Assumptions & Gaps' })}
                </div>
                <div className="space-y-3">
                  <div>
                    <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--ss-text-muted)' }}>
                      {t('createExperiment.customBuilder.assumptionsTitle', { defaultValue: 'Assumptions' })}
                    </div>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm" style={{ color: 'var(--ss-text)' }}>
                      {assumptions.length > 0 ? assumptions.map((item, index) => <li key={`${item}-${index}`}>{item}</li>) : <li>{t('createExperiment.customBuilder.noAssumptions', { defaultValue: 'No assumptions reported.' })}</li>}
                    </ul>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--ss-text-muted)' }}>
                      {t('createExperiment.customBuilder.missingInfoTitle', { defaultValue: 'Missing Information' })}
                    </div>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm" style={{ color: 'var(--ss-text)' }}>
                      {missingInformation.length > 0 ? missingInformation.map((item, index) => <li key={`${item}-${index}`}>{item}</li>) : <li>{t('createExperiment.customBuilder.noMissingInfo', { defaultValue: 'No obvious gaps reported.' })}</li>}
                    </ul>
                  </div>
                  {analysisWarnings.length > 0 ? (
                    <div>
                      <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--ss-text-muted)' }}>
                        {t('createExperiment.customBuilder.analysisWarningsTitle', { defaultValue: 'System Warnings' })}
                      </div>
                      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm" style={{ color: 'var(--ss-text)' }}>
                        {analysisWarnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}
                      </ul>
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
                <div className="space-y-3">
                  <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                    {t('createExperiment.customBuilder.supportingPassagesTitle', { defaultValue: 'Supporting Passages' })}
                  </div>
                  {sourceSections.length > 0 ? (
                    <div className="grid gap-3">
                      {sourceSections.map((section) => (
                        <div data-testid="research-source-section" key={section.id} className="rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>{section.title}</div>
                            {section.page ? <div className="text-xs" style={{ color: 'var(--ss-text-muted)' }}>{t('createExperiment.customBuilder.pageShort', { defaultValue: 'p. {{page}}', page: section.page })}</div> : null}
                          </div>
                          <p className="mt-2 text-sm leading-6" style={{ color: 'var(--ss-text)' }}>{section.excerpt}</p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-dashed p-4 text-sm" style={{ borderColor: 'var(--ss-border-strong)', color: 'var(--ss-text-muted)' }}>
                      {t('createExperiment.customBuilder.noSourceSections', { defaultValue: 'Upload a document or run analysis to see extracted sections here.' })}
                    </div>
                  )}
                </div>

                <div className="space-y-3">
                  <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                    {t('createExperiment.customBuilder.evidenceChecklistTitle', { defaultValue: 'Why the system suggested this draft' })}
                  </div>
                  {evidence.length > 0 ? (
                    <div className="space-y-3">
                      {evidence.map((item, index) => (
                        <div data-testid="research-evidence-card" key={`${item.label}-${index}`} className="rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
                          <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>{item.label}</div>
                          <p className="mt-2 text-sm leading-6" style={{ color: 'var(--ss-text)' }}>{item.snippet}</p>
                          {item.section ? <div className="mt-2 text-xs" style={{ color: 'var(--ss-text-muted)' }}>{item.section}</div> : null}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-dashed p-4 text-sm" style={{ borderColor: 'var(--ss-border-strong)', color: 'var(--ss-text-muted)' }}>
                      {t('createExperiment.customBuilder.noEvidence', { defaultValue: 'Run analysis to collect supporting snippets from the source.' })}
                    </div>
                  )}
                </div>
              </div>

              {sourcePages.length > 0 ? (
                <div className="space-y-2">
                  <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                    {t('createExperiment.customBuilder.pagePreviewTitle', { defaultValue: 'OCR / Page Extraction Preview' })}
                  </div>
                  <div className="grid gap-3 lg:grid-cols-2">
                    {sourcePages.slice(0, 4).map((page) => (
                      <div data-testid="research-page-preview" key={page.page_number} className="rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
                        <div className="mb-2 flex items-center justify-between gap-3">
                          <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                            {t('createExperiment.customBuilder.pageLabel', { defaultValue: 'Page {{page}}', page: page.page_number })}
                          </div>
                          <div className="text-xs" style={{ color: 'var(--ss-text-muted)' }}>
                            {localizedExtractionMethod(page.method, t)} · {page.char_count}
                          </div>
                        </div>
                        <p className="text-sm leading-6" style={{ color: 'var(--ss-text)' }}>
                          {page.text.slice(0, 500) || t('createExperiment.customBuilder.emptyPage', { defaultValue: 'No text extracted from this page.' })}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {sourceAsset && sourceDocumentQuality ? (
                <div className="rounded-2xl border p-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
                  <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                    {t('createExperiment.customBuilder.documentInsightsTitle', { defaultValue: 'Document extraction snapshot' })}
                  </div>
                  <div className="mt-1 text-sm" style={{ color: 'var(--ss-text-muted)' }}>
                    {t('createExperiment.customBuilder.documentInsightsHint', { defaultValue: 'Check whether the source extraction itself looks clean before trusting the reconstructed experiment draft.' })}
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    {sourceAsset.extracted_title ? (
                      <div>
                        <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--ss-text-muted)' }}>
                          {t('createExperiment.customBuilder.documentTitleLabel', { defaultValue: 'Extracted title' })}
                        </div>
                        <div className="mt-1 text-sm" style={{ color: 'var(--ss-text)' }}>{sourceAsset.extracted_title}</div>
                      </div>
                    ) : null}
                    {sourceAsset.extracted_abstract ? (
                      <div>
                        <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--ss-text-muted)' }}>
                          {t('createExperiment.customBuilder.documentAbstractLabel', { defaultValue: 'Extracted abstract' })}
                        </div>
                        <div className="mt-1 text-sm line-clamp-4" style={{ color: 'var(--ss-text)' }}>{sourceAsset.extracted_abstract}</div>
                      </div>
                    ) : null}
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    <div className="rounded-xl border px-3 py-2" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)' }}>
                      <div className="text-xs" style={{ color: 'var(--ss-text-muted)' }}>{t('createExperiment.customBuilder.documentSectionsLabel', { defaultValue: 'Weighted sections' })}</div>
                      <div className="mt-1 text-sm font-medium" style={{ color: 'var(--ss-text)' }}>{sourceDocumentQuality.section_count ?? 0}</div>
                    </div>
                    <div className="rounded-xl border px-3 py-2" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)' }}>
                      <div className="text-xs" style={{ color: 'var(--ss-text-muted)' }}>{t('createExperiment.customBuilder.documentPageQualityLabel', { defaultValue: 'Avg page quality' })}</div>
                      <div className="mt-1 text-sm font-medium" style={{ color: 'var(--ss-text)' }}>{typeof sourceDocumentQuality.average_page_quality === 'number' ? sourceDocumentQuality.average_page_quality.toFixed(2) : '—'}</div>
                    </div>
                    <div className="rounded-xl border px-3 py-2" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)' }}>
                      <div className="text-xs" style={{ color: 'var(--ss-text-muted)' }}>{t('createExperiment.customBuilder.documentOcrLabel', { defaultValue: 'OCR used' })}</div>
                      <div className="mt-1 text-sm font-medium" style={{ color: 'var(--ss-text)' }}>{sourceDocumentQuality.ocr_used ? t('common.yes', { defaultValue: 'Yes' }) : t('common.no', { defaultValue: 'No' })}</div>
                    </div>
                    <div className="rounded-xl border px-3 py-2" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)' }}>
                      <div className="text-xs" style={{ color: 'var(--ss-text-muted)' }}>{t('createExperiment.customBuilder.documentReferencesLabel', { defaultValue: 'References stripped' })}</div>
                      <div className="mt-1 text-sm font-medium" style={{ color: 'var(--ss-text)' }}>{sourceDocumentQuality.has_references ? t('common.yes', { defaultValue: 'Yes' }) : t('common.no', { defaultValue: 'No' })}</div>
                    </div>
                    <div className="rounded-xl border px-3 py-2" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)' }}>
                      <div className="text-xs" style={{ color: 'var(--ss-text-muted)' }}>{t('createExperiment.customBuilder.documentFigureCaptionsLabel', { defaultValue: 'Figure captions' })}</div>
                      <div className="mt-1 text-sm font-medium" style={{ color: 'var(--ss-text)' }}>{sourceAsset.extracted_figure_captions?.length ?? 0}</div>
                    </div>
                    <div className="rounded-xl border px-3 py-2" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-surface)' }}>
                      <div className="text-xs" style={{ color: 'var(--ss-text-muted)' }}>{t('createExperiment.customBuilder.documentTableCaptionsLabel', { defaultValue: 'Table captions' })}</div>
                      <div className="mt-1 text-sm font-medium" style={{ color: 'var(--ss-text)' }}>{sourceAsset.extracted_table_captions?.length ?? 0}</div>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
              </CollapsibleCardSection>
            </div>
          </CollapsibleCardSection>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border px-5 py-4" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-surface)' }}>
          <div className="text-sm" style={{ color: 'var(--ss-text)' }}>
            {t('createExperiment.customBuilder.continueHint', { defaultValue: 'The extracted draft will be written into the standard builder next. Before continuing, please manually check and adjust the scenario, settings, actions, roles, and chosen path as needed.' })}
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" onClick={() => navigate('/simulations/create')}>
              {t('common.back', { defaultValue: 'Back' })}
            </Button>
            <Button data-testid="research-continue-button" onClick={() => void applyBuilderState()} disabled={isAnalyzing || isUploading || isApplying}>
              {isApplying ? t('common.loading', { defaultValue: 'Loading' }) : t('createExperiment.customBuilder.continue', { defaultValue: 'Continue to Builder' })}
              <ArrowRight size={16} />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default CreateExperimentCustomPage;
