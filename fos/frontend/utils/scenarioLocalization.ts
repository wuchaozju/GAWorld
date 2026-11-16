/**
 * Scenario localization utilities for i18n.
 *
 * Provides functions to look up localized scenario names, descriptions,
 * parameter labels, and category labels using i18next translation keys.
 *
 * Exports: getLocalizedScenarioName, getLocalizedScenarioDescription,
 *   getLocalizedSimulationSceneLabel, getLocalizedParamLabel,
 *   getLocalizedParamHint, getScenarioCategoryLabel
 */
import type { TFunction } from "i18next";

import type { ScenarioData, ScenarioParam } from "../services/scenarios";

type ScenarioLike = Pick<ScenarioData, "id" | "category" | "name" | "description">;
type SceneConfig = Record<string, unknown> | null | undefined;

const DEFAULT_DESCRIPTION_LENGTH = 30;

const truncateScenarioDescription = (description: string, maxLength = DEFAULT_DESCRIPTION_LENGTH) =>
  description.length > maxLength ? `${description.slice(0, maxLength)}...` : description;

export const getLocalizedScenarioName = (t: TFunction, scenario: ScenarioLike | null | undefined) => {
  if (!scenario) {
    return "";
  }

  return t(`scenario.${scenario.category}.${scenario.id}.name`, {
    defaultValue: scenario.name,
  });
};

export const getLocalizedScenarioDescription = (
  t: TFunction,
  scenario: ScenarioLike | null | undefined,
) => {
  if (!scenario) {
    return "";
  }

  return t(`scenario.${scenario.category}.${scenario.id}.description`, {
    defaultValue: scenario.description,
  });
};

export const getLocalizedActionName = (actionName: string, isZh: boolean) => {
  if (!isZh) {
    return actionName;
  }

  const source = actionName.trim().toLowerCase();

  if (!source) {
    return "动作";
  }

  if (/^cooperate$|协作|合作/.test(source)) {
    return "合作";
  }
  if (/^defect$|背叛|betray|compete/.test(source)) {
    return "背叛";
  }
  if (/silent|silence|stay silent|保持沉默|沉默/.test(source)) {
    return "沉默";
  }
  if (/confess|testify|report|指认|招供/.test(source)) {
    return "指认";
  }
  if (/opera|歌剧|ballet|芭蕾/.test(source)) {
    return "歌剧";
  }
  if (/football|soccer|足球/.test(source)) {
    return "足球";
  }
  if (/stag|猎鹿/.test(source)) {
    return "猎鹿";
  }
  if (/hare|rabbit|猎兔/.test(source)) {
    return "猎兔";
  }
  if (/contribute|contribution|贡献/.test(source)) {
    return "贡献";
  }
  if (/share|sharing|分享/.test(source)) {
    return "分享";
  }
  if (/move|移动/.test(source)) {
    return "移动";
  }
  if (/look around|observe|观察/.test(source)) {
    return "观察";
  }
  if (/gather|collect|收集/.test(source)) {
    return "采集";
  }
  if (/rest|等待|休息/.test(source)) {
    return "等待";
  }
  if (/speak|发言|表达/.test(source)) {
    return "发言";
  }
  if (/call vote|发起表决/.test(source)) {
    return "发起表决";
  }
  if (/vote yes|赞成/.test(source)) {
    return "赞成";
  }
  if (/vote no|反对/.test(source)) {
    return "反对";
  }
  if (/abstain|弃权/.test(source)) {
    return "弃权";
  }
  if (/vote|投票/.test(source)) {
    return "投票";
  }
  if (/heads|正面/.test(source)) {
    return "正面";
  }
  if (/tails|反面/.test(source)) {
    return "反面";
  }
  if (/action 1/.test(source)) {
    return "动作一";
  }
  if (/action 2/.test(source)) {
    return "动作二";
  }

  return actionName;
};

export const getLocalizedActionDescription = (description: string, isZh: boolean) => {
  if (!isZh) {
    return description;
  }

  const source = description.trim().toLowerCase();

  if (!source) {
    return "";
  }

  const chooseMatch = source.match(/^choose\s+(.+)$/);
  if (chooseMatch) {
    return `选择${getLocalizedActionName(chooseMatch[1], true)}`;
  }

  if (/go to the opera|opera|go to the ballet|ballet/.test(source)) {
    return "去看歌剧";
  }
  if (/go to the football game|football|soccer/.test(source)) {
    return "去看足球比赛";
  }
  if (/hunt the stag|stag/.test(source)) {
    return "猎鹿（需要所有人合作）";
  }
  if (/hunt the hare|hare|rabbit/.test(source)) {
    return "猎兔（安全但收益较低）";
  }
  if (/work together with your partner|mutual benefit|cooperate with|合作/.test(source)) {
    return "与搭档合作，争取共同收益";
  }
  if (/pursue your own interest|self-interest|defect|betray|背叛/.test(source)) {
    return "优先追求自身利益";
  }
  if (/contribute.*shared pool|shared pool|共享池|contribute/.test(source)) {
    return "向共享池投入资源";
  }
  if (/help|support/.test(source)) {
    return "为他人提供支持";
  }
  if (/move to a location|adjacent cell|move/.test(source)) {
    return "移动到新的位置";
  }
  if (/observe surroundings|look around/.test(source)) {
    return "观察周围环境";
  }
  if (/collect a resource|gather/.test(source)) {
    return "收集附近资源";
  }
  if (/do nothing this turn|rest/.test(source)) {
    return "本回合暂不行动";
  }
  if (/say something to the group|make a statement|share your thoughts|speak/.test(source)) {
    return "向其他参与者表达观点";
  }
  if (/initiate a vote|call vote/.test(source)) {
    return "发起一次表决";
  }
  if (/vote in favor/.test(source)) {
    return "投票支持当前提案";
  }
  if (/vote against/.test(source)) {
    return "投票反对当前提案";
  }
  if (/neither yes nor no|abstain/.test(source)) {
    return "暂不表态，选择弃权";
  }
  if (/vote to eliminate a suspect/.test(source)) {
    return "投票淘汰一名嫌疑对象";
  }
  if (/talk to a nearby agent.*transmit contagion/.test(source)) {
    return "与附近代理交谈，并可能传播感染";
  }
  if (/observe|inspect/.test(source)) {
    return "观察并收集信息";
  }

  return description;
};

export const getScenarioParamDefinition = (
  scenario: ScenarioData | null | undefined,
  key: string,
) => scenario?.parameters.find((param) => param.key === key) ?? null;

export const getScenarioParamOptionLabel = (
  param: ScenarioParam | null | undefined,
  value: unknown,
) => {
  if (!param?.options) {
    return value;
  }

  const match = param.options.find((option) => option === value);

  if (!match) {
    return value;
  }

  return match;
};

export const formatScenarioParamValue = (
  scenario: ScenarioData | null | undefined,
  key: string,
  value: unknown,
) => {
  const param = getScenarioParamDefinition(scenario, key);
  const resolved = getScenarioParamOptionLabel(param, value);

  if (Array.isArray(resolved)) {
    return resolved.join(", ");
  }
  if (resolved === null || resolved === undefined || resolved === "") {
    return "—";
  }
  return String(resolved);
};

export const buildScenarioTitle = (
  scenarioName: string,
  scenarioDescription: string,
  maxLength = DEFAULT_DESCRIPTION_LENGTH,
) => {
  if (!scenarioDescription.trim()) {
    return scenarioName;
  }

  return `${scenarioName} - ${truncateScenarioDescription(scenarioDescription, maxLength)}`;
};

export const getScenarioIdFromSceneConfig = (sceneConfig: SceneConfig) => {
  const genericConfig = (sceneConfig?.generic_config ?? null) as Record<string, unknown> | null;
  return String(sceneConfig?.scenario_id ?? genericConfig?.scenario_id ?? "").trim() || null;
};

export const findScenarioBySceneConfig = (
  sceneConfig: SceneConfig,
  scenarios: ScenarioData[],
) => {
  const scenarioId = getScenarioIdFromSceneConfig(sceneConfig);
  return scenarios.find((scenario) => scenario.id === scenarioId) ?? null;
};

export const getLocalizedSimulationName = (
  t: TFunction,
  simulationName: string,
  sceneConfig: SceneConfig,
  scenarios: ScenarioData[],
) => {
  const matchedScenario = findScenarioBySceneConfig(sceneConfig, scenarios);
  if (!matchedScenario) {
    return simulationName;
  }

  const rawScenarioName = matchedScenario.name;
  const rawScenarioDescription = matchedScenario.description;
  const localizedScenarioName = getLocalizedScenarioName(t, matchedScenario);
  const localizedScenarioDescription = getLocalizedScenarioDescription(t, matchedScenario);
  const rawDefaultTitle = buildScenarioTitle(rawScenarioName, rawScenarioDescription);
  const localizedDefaultTitle = buildScenarioTitle(
    localizedScenarioName,
    localizedScenarioDescription,
  );

  if (simulationName === rawDefaultTitle) {
    return localizedDefaultTitle;
  }

  if (simulationName === rawScenarioName) {
    return localizedScenarioName;
  }

  const rawPrefix = `${rawScenarioName} - `;
  if (simulationName.startsWith(rawPrefix)) {
    const suffix = simulationName.slice(rawPrefix.length);
    const rawDefaultSuffix = truncateScenarioDescription(rawScenarioDescription);
    if (suffix === rawDefaultSuffix) {
      return localizedDefaultTitle;
    }
    return `${localizedScenarioName} - ${suffix}`;
  }

  return simulationName;
};

export const getLocalizedSimulationSceneLabel = (
  t: TFunction,
  sceneConfig: SceneConfig,
  scenarios: ScenarioData[],
  fallbackLabel: string,
) => {
  const matchedScenario = findScenarioBySceneConfig(sceneConfig, scenarios);
  if (!matchedScenario) {
    return fallbackLabel;
  }

  return getLocalizedScenarioName(t, matchedScenario);
};
