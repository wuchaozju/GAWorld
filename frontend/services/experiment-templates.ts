/**
 * Experiment Templates API Service
 *
 * Handles API calls for the Three-Layer Experiment Platform.
 * Provides functions to fetch available action types, create experiment templates,
 * and run experiments using the new structured action system.
 */

import { apiDelete, apiGet, apiPost } from './client';
import i18n from '../i18n';
import type { ScenarioData } from './scenarios';

// =============================================================================
// Types
// =============================================================================

/**
 * Action type definition matching backend schema
 */
export interface ActionType {
  value: string;
  label: string;
  description: string;
}

/**
 * Response from /action-types endpoint
 */
export interface AvailableActionsResponse {
  actions: ActionType[];
}

/**
 * Request payload for creating an experiment template
 */
export interface CreateTemplateRequest {
  name: string;
  description: string;
  actions: TemplateAction[];
  settings: TemplateSettings;
}

/**
 * Action definition for template creation
 */
export interface TemplateAction {
  action_type: string;
  name: string;
  description: string;
  custom_action_name?: string;
  parameters?: ActionParameter[];
}

/**
 * Action parameter definition
 */
export interface ActionParameter {
  name: string;
  type: string;
  description: string;
  required: boolean;
}

/**
 * Template settings
 */
export interface TemplateSettings {
  scenario_id?: string;
  round_visibility: 'simultaneous' | 'sequential';
  max_rounds?: number;
  [key: string]: unknown;
}

export interface ExperimentTemplateRecord {
  id: number;
  name: string;
  description: string;
  actions: Array<{
    name: string;
    description?: string;
    parameters?: ActionParameter[];
  }>;
  settings: TemplateSettings;
  created_at: string;
  updated_at: string;
}

export interface ListExperimentTemplatesResponse {
  templates: ExperimentTemplateRecord[];
  count: number;
}

/**
 * Request payload for running an experiment
 */
export interface RunExperimentRequest {
  template_id: number | null;
  agents: any[];
  llm_config: any;
}

/**
 * Response from experiment creation/run
 */
export interface ExperimentRunResponse {
  experiment_id: number;
  message?: string;
}

// =============================================================================
// Action Type Mapping
// =============================================================================

/**
 * Map action names to ActionType enum values
 */
const ACTION_TYPE_MAPPING: Record<string, string> = {
  'cooperate': 'cooperate',
  'defect': 'defect',
  'conform': 'conform',
  'betray': 'defect',
  'invest': 'invest',
  'withdraw': 'withdraw',
  'share': 'share',
  'keep': 'keep',
  'move_left': 'move_left',
  'move_right': 'move_right',
  'stay': 'stay',
  'vote_yes': 'vote_yes',
  'vote_no': 'vote_no',
  'abstain': 'abstain',
  'speak': 'speak',
};

/**
 * Get the ActionType enum value for an action name
 */
export function getActionType(actionName: string): string {
  return ACTION_TYPE_MAPPING[actionName.toLowerCase()] || 'custom';
}

/**
 * Get the description for an action name via i18n.
 * Falls back to the action name if no translation is found.
 */
export function getActionDescription(actionName: string): string {
  const key = `actionDescriptions.${actionName.toLowerCase()}`;
  const translation = i18n.t(key);
  return translation !== key ? translation : actionName;
}

// =============================================================================
// API Functions
// =============================================================================

/**
 * Fetch available action types from backend
 * GET /api/experiment-templates/action-types
 */
export async function fetchAvailableActionTypes(): Promise<AvailableActionsResponse> {
  return apiGet<AvailableActionsResponse>('/experiment-templates/action-types');
}

/**
 * Create a new experiment template
 * POST /api/experiment-templates/templates
 */
export async function createExperimentTemplate(
  data: CreateTemplateRequest
): Promise<ExperimentTemplateRecord> {
  return apiPost<ExperimentTemplateRecord>('/experiment-templates/templates', data);
}

/**
 * List experiment templates for current user.
 * GET /api/experiment-templates/templates
 */
export async function listExperimentTemplates(): Promise<ListExperimentTemplatesResponse> {
  return apiGet<ListExperimentTemplatesResponse>('/experiment-templates/templates');
}

/**
 * Run an experiment from a template
 * POST /api/experiment-templates/run
 */
export async function runExperiment(
  data: RunExperimentRequest
): Promise<ExperimentRunResponse> {
  return apiPost<ExperimentRunResponse>('/experiment-templates/run', data);
}

/**
 * Delete an experiment template
 * DELETE /api/experiment-templates/templates/:id
 */
export async function deleteExperimentTemplate(id: number): Promise<void> {
  return apiDelete<void>(`/experiment-templates/templates/${id}`);
}

export interface PersonalTemplateScenarioData extends ScenarioData {
  templateSource: 'user_template';
  templateId: number;
  templateSettings: TemplateSettings;
}

export function mapExperimentTemplateToScenario(template: ExperimentTemplateRecord): PersonalTemplateScenarioData {
  const roundVisibility = template.settings?.round_visibility === 'simultaneous'
    ? 'simultaneous'
    : 'sequential';

  return {
    id: `user-template:${template.id}`,
    name: template.name,
    category: 'custom',
    description: template.description,
    interaction_mode: roundVisibility,
    display_type: 'params',
    parameters: [],
    actions: template.actions.map((action) => ({
      name: action.name,
      description: action.description || action.name,
    })),
    category_actions: template.actions.map((action) => ({
      name: action.name,
      description: action.description || action.name,
    })),
    default_action_ids: template.actions.map((action) => action.name),
    templateSource: 'user_template',
    templateId: template.id,
    templateSettings: template.settings || { round_visibility: roundVisibility },
  };
}
