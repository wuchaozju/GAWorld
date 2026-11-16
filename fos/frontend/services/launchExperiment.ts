/**
 * This file turns the experiment builder's saved choices into a new simulation.
 *
 * launchExperimentFromBuilderState reads the builder, prepares agents and actions,
 * creates the simulation, and shows a success message.
 */

import type { TFunction } from "i18next";

import { useExperimentBuilder, type ManualAgentType } from "../store/experiment-builder";
import type { AppState } from "../store";
import type { Agent, GenericTemplateConfig, SimulationTemplate } from "../types";
import {
  buildScenarioTitle,
  getLocalizedScenarioDescription,
  getLocalizedScenarioName,
} from "../utils/scenarioLocalization";
import { isPolicyCascadeScenario } from "../utils/policyCascade";

interface LaunchDependencies {
  t: TFunction;
  addSimulation: AppState["addSimulation"];
  addNotification: AppState["addNotification"];
}

function buildAgents(agentType: ManualAgentType): Agent[] {
  const state = useExperimentBuilder.getState();
  const count = agentType.count || 1;

  return Array.from({ length: count }, (_, index) => {
    const rolePrompt = agentType.rolePrompt.trim();
    const userProfile = agentType.userProfile.trim();
    const suffix = count > 1 ? ` ${index + 1}` : "";
    const idSuffix = count > 1 ? `-${index}` : "";
    const propertyAvatar = agentType.properties.avatarUrl;
    const avatarUrl = typeof propertyAvatar === "string"
      ? propertyAvatar
      : `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(agentType.label) + index}`;
    const providerId = agentType.providerId ?? state.selectedProviderId ?? undefined;
    const provider = state.llmProviders.find((item) => item.id === providerId);
    const llmConfig = {
      provider: provider?.provider || "backend",
      model: provider?.model || "default",
    };

    return {
      id: `${agentType.id}${idSuffix}`,
      name: `${agentType.label}${suffix}`,
      role: rolePrompt,
      avatarUrl,
      profile: userProfile,
      llmConfig,
      provider_id: providerId,
      properties: { ...agentType.properties, avatarUrl },
      history: {},
      memory: [],
      knowledgeBase: [],
    };
  });
}

function buildTemplate(t: TFunction): { name: string; template: SimulationTemplate } {
  const state = useExperimentBuilder.getState();
  const scenario = state.selectedScenarioData;
  const localizedName = getLocalizedScenarioName(t, scenario);
  const localizedDescription = getLocalizedScenarioDescription(t, scenario);
  const scenarioName = localizedName || t("experimentBuilder.newExperiment");
  const description = state.scenarioDescription.trim()
    || localizedDescription
    || t("experimentBuilder.customExperiment");
  const customTurnOrdering = state.roundVisibility === "random"
    ? "random_sequential"
    : state.roundVisibility;
  const parameters = {
    ...state.scenarioParams,
    ...(state.selectedScenarioId === "custom"
      ? { custom_prompt: description, turn_ordering: customTurnOrdering }
      : {}),
  };
  const actions = state.availableActions
    .filter((action) => state.selectedActionIds.includes(action.name))
    .map((action) => ({ name: action.name, description: action.description || action.name }));
  const genericConfig = {
    description,
    scenario_id: state.selectedScenarioId || "custom",
    actions,
    parameters,
    round_visibility: state.roundVisibility,
  } as unknown as GenericTemplateConfig;
  const isPolicyCascade = isPolicyCascadeScenario(scenario);
  const experimentCategories = new Set([
    "game_theory", "discussion", "grid", "sociology", "social_deduction",
    "spatial", "generative_city", "custom",
  ]);
  const name = buildScenarioTitle(String(scenarioName), String(description));

  return {
    name,
    template: {
      id: "experiment-template",
      name,
      description: String(description),
      category: scenario ? "system" : "custom",
      sceneType: isPolicyCascade
        ? "policy_cascade_scene"
        : experimentCategories.has(scenario?.category || "") ? "experiment" : "generic",
      agents: state.agentTypes.flatMap(buildAgents),
      defaultTimeConfig: {
        baseTime: new Date().toISOString(),
        unit: "hour",
        step: 1,
      },
      genericConfig,
      defaultNetwork: state.socialNetwork,
    },
  };
}

export function launchExperimentFromBuilderState({
  t,
  addSimulation,
  addNotification,
}: LaunchDependencies): void {
  const { name, template } = buildTemplate(t);
  addSimulation(name, template);
  addNotification("success", t("experimentBuilder.experimentCreated"));
}
