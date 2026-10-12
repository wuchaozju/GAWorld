import i18n from '../../i18n';
import type { Agent } from '../../types';
import { isZh, pickText } from './time';

const ACTION_LABELS: Record<'en' | 'zh', Record<string, string>> = {
  en: {
    cooperate: 'Cooperate',
    defect: 'Defect',
    contribute: 'Contribute',
    allocate: 'Allocate',
    keep: 'Keep',
    reduce: 'Reduce',
    opera: 'Opera',
    football: 'Football',
    stag: 'Stag',
    hare: 'Hare',
    look_around: 'Look around',
    move: 'Move',
    move_to_location: 'Move to location',
    send_message: 'Send message',
    speak: 'Speak',
    rest: 'Rest',
    yield: 'Yield',
    comply_publicly: 'Publicly comply',
    comply_covertly_resist: 'Comply but resist privately',
    resist_openly: 'Openly resist',
    persuade_others: 'Persuade others',
    form_coalition: 'Form coalition',
    transmit_faithfully: 'Transmit faithfully',
    reinterpret_downward: 'Reinterpret downward',
    comply_directive: 'Comply with directive',
    resist_quietly: 'Quietly resist',
    report_up: 'Report upward',
    create_workaround: 'Create workaround',
    express_opinion: 'Express opinion',
    reinforce_ingroup: 'Reinforce in-group',
    challenge_outgroup: 'Challenge out-group',
    seek_common_ground: 'Seek common ground',
    share_content: 'Share content',
    disengage: 'Disengage',
    share_resources: 'Share resources',
    hoard: 'Hoard',
    propose_trade: 'Propose trade',
    form_contract: 'Form contract',
    honor_contract: 'Honor contract',
    defect_from_contract: 'Defect from contract',
    enroll_self: 'Enroll self',
    enroll_family: 'Enroll family',
    wait_and_observe: 'Wait and observe',
    decline_for_now: 'Decline for now',
  },
  zh: {
    cooperate: '合作',
    defect: '背叛',
    contribute: '贡献',
    allocate: '分配',
    keep: '保留',
    reduce: '扣减',
    opera: '歌剧',
    football: '足球',
    stag: '猎鹿',
    hare: '猎兔',
    look_around: '环顾四周',
    move: '移动',
    move_to_location: '移动到位置',
    send_message: '发送消息',
    speak: '发言',
    rest: '休息',
    yield: '结束本轮发言',
    comply_publicly: '公开遵守',
    comply_covertly_resist: '表面遵守，私下抵制',
    resist_openly: '公开抵制',
    persuade_others: '说服他人',
    form_coalition: '组建联盟',
    transmit_faithfully: '忠实传达',
    reinterpret_downward: '向下改写',
    comply_directive: '遵守指令',
    resist_quietly: '悄悄抵制',
    report_up: '向上报告',
    create_workaround: '建立变通路径',
    express_opinion: '表达观点',
    reinforce_ingroup: '强化群内认同',
    challenge_outgroup: '挑战外群观点',
    seek_common_ground: '寻找共同点',
    share_content: '分享内容',
    disengage: '退出接触',
    share_resources: '分享资源',
    hoard: '囤积资源',
    propose_trade: '提议交易',
    form_contract: '建立协议',
    honor_contract: '履行协议',
    defect_from_contract: '违背协议',
    enroll_self: '为自己投保',
    enroll_family: '为家人投保',
    wait_and_observe: '继续观望',
    decline_for_now: '暂不投保',
  },
};

const GENERIC_AGENT_LABEL = /^(?:\d+|agent-[\w-]+|a-\d+-.*)$/i;

const extractAgentOrdinal = (value: string): string => {
  const text = String(value || '').trim();
  const match = text.match(/(\d+)(?!.*\d)/);
  return match?.[1] || '';
};

const translateActionExecution = (agentName: string, actionName: string | undefined): string => {
  if (!actionName) {
    return pickText(`${agentName} chose an action`, `${agentName}做出了一个选择`);
  }

  const key = `actions.${actionName}.execute`;
  const translated = i18n.t(key, {
    agent_name: agentName,
    defaultValue: '',
  });

  if (translated && translated !== key) {
    return translated;
  }

  const readableAction = translateActionName(actionName);
  return pickText(
    `${agentName} chose ${readableAction}`,
    `${agentName}选择了${readableAction}`,
  );
};

const formatExperimentParameterValue = (value: unknown): string => {
  if (typeof value === 'string') {
    return translateActionName(value);
  }
  return JSON.stringify(value);
};

export const formatExperimentParameters = (parameters: Record<string, unknown>): string => {
  const meaningfulParams = Object.entries(parameters).filter(([, value]) => value !== null && value !== undefined && value !== '');
  if (meaningfulParams.length === 0) {
    return '';
  }

  return meaningfulParams
    .map(([key, value]) => `${key}=${formatExperimentParameterValue(value)}`)
    .join(', ');
};

export const extractSummaryParameterText = (summary: string): string => {
  const match = summary.match(/\((.*)\)/);
  return match?.[1]?.trim() || '';
};

export const formatExperimentNarrative = (agentName: string, text: string): string => {
  const narrative = String(text || '').trim();
  if (!narrative) {
    return '';
  }
  return pickText(`${agentName}: ${narrative}`, `${agentName}：${narrative}`);
};

const normalizePlanMarkers = (text: string): string => {
  if (!text) return '';
  if (!isZh()) return text;
  let normalized = text;
  normalized = normalized.replace(/\[CURRENT\]/g, '[当前]');
  normalized = normalized.replace(/\[Done\]/gi, '[已完成]');
  normalized = normalized.replace(/\[DONE\]/g, '[已完成]');
  return normalized;
};

const stripActionXml = (raw: string): string => {
  if (!raw) return '';
  let text = raw;
  text = text.replace(/<Action[\s\S]*?<\/Action>/gi, '');
  text = text.replace(/<Action[^>]*\/>/gi, '');
  text = text.replace(/<\/?(message|messages|youshould_send_message)[^>]*>/gi, '');
  text = text.replace(/<[^>]+>/g, '');
  return text.trim();
};

const prettifyAssistantCtx = (content: string): string => {
  if (!content) return '';
  const cleaned = stripActionXml(content);

  const thoughtsMatch = cleaned.match(/--- Thoughts ---\s*([\s\S]*?)\s*--- Plan ---/);
  const planMatch = cleaned.match(/--- Plan ---\s*([\s\S]*?)(?:\n--- Action ---|\n--- Plan Update ---|\n--- Emotion Update ---|\s*$)/);

  const rawThoughts = thoughtsMatch && thoughtsMatch[1] ? thoughtsMatch[1].trim() : '';
  const rawPlan = planMatch && planMatch[1] ? planMatch[1].trim() : '';

  const thoughts = translateAgentContent(normalizePlanMarkers(rawThoughts));
  const plan = translateAgentContent(normalizePlanMarkers(rawPlan));

  if (!thoughts && !plan) {
    return translateAgentContent(normalizePlanMarkers(cleaned));
  }

  let output = '';
  if (thoughts) {
    output += `【思考】\n${thoughts}`;
  }
  if (plan) {
    if (output) {
      output += '\n\n';
    }
    output += `【计划】\n${plan}`;
  }
  return output;
};

export const translateActionName = (name: string | undefined): string => {
  if (!name) return pickText('Unknown action', '未知动作');
  const lang = isZh() ? 'zh' : 'en';
  return ACTION_LABELS[lang][name] || ACTION_LABELS.en[name] || name;
};

export const isGenericAgentLabel = (value: string | undefined | null): boolean => {
  const text = String(value || '').trim();
  return !text || GENERIC_AGENT_LABEL.test(text);
};

export const getAgentDisplayName = (agent: Partial<Agent> | null | undefined): string => {
  if (!agent) {
    return pickText('Unknown agent', '未知参与者');
  }

  const name = String(agent.name || '').trim();
  const role = String(agent.role || '').trim();

  if (name && !isGenericAgentLabel(name)) {
    return name;
  }

  if (role && role !== name && !isGenericAgentLabel(role)) {
    return role;
  }

  const ordinal = extractAgentOrdinal(name || String(agent.id || ''));
  if (ordinal) {
    return pickText(`Participant ${ordinal}`, `${ordinal}号参与者`);
  }

  return pickText('Participant', '参与者');
};

export const getAgentDisplayRole = (agent: Partial<Agent> | null | undefined): string => {
  if (!agent) {
    return pickText('Participant in current simulation', '参与当前实验');
  }

  const name = String(agent.name || '').trim();
  const role = String(agent.role || '').trim();

  if (role && role !== name && !isGenericAgentLabel(role)) {
    return role;
  }

  return pickText('Participant in current simulation', '参与当前实验');
};

export const resolveAgentDisplayName = (
  agentRef: string | undefined,
  agents: Partial<Agent>[],
): string => {
  if (!agentRef) {
    return pickText('System', '系统');
  }

  const matchedAgent = agents.find((agent) => agent.id === agentRef || agent.name === agentRef) || null;
  if (matchedAgent) {
    return getAgentDisplayName(matchedAgent);
  }

  if (!isGenericAgentLabel(agentRef)) {
    return agentRef;
  }

  const ordinal = extractAgentOrdinal(agentRef);
  if (ordinal) {
    return pickText(`Participant ${ordinal}`, `${ordinal}号参与者`);
  }

  return pickText('Participant', '参与者');
};

export const buildTranslatedActionExecution = (agentName: string, actionName: string | undefined): string => {
  return translateActionExecution(agentName, actionName);
};

export const translateAgentContent = (text: string): string => {
  if (!text) return '';
  if (!isZh()) return text;
  let translated = text;

  translated = translated.replace(/My role is (the )?/gi, '我的角色是');
  translated = translated.replace(/I am (the )?/gi, '我是');
  translated = translated.replace(/I'm (the )?/gi, '我是');
  translated = translated.replace(/focusing on/gi, '专注于');
  translated = translated.replace(/as (the )?/gi, '作为');
  translated = translated.replace(/\bthe Speaker\b/gi, '发言人');
  translated = translated.replace(/\bthe Moderator\b/gi, '主持人');

  translated = translated.replace(/My (immediate )?focus is (to )?/gi, '我的（当前）重点是');
  translated = translated.replace(/My goal is (to )?/gi, '我的目标是');
  translated = translated.replace(/My goals? (are|is)/gi, '我的目标是');
  translated = translated.replace(/I need to/gi, '我需要');
  translated = translated.replace(/I will/gi, '我将');
  translated = translated.replace(/I should/gi, '我应该');

  translated = translated.replace(/\bensure\b/gi, '确保');
  translated = translated.replace(/\bfacilitate\b/gi, '促进');
  translated = translated.replace(/\bmaintain\b/gi, '维持');
  translated = translated.replace(/\bestablish\b/gi, '建立');

  translated = translated.replace(/\[当前\]/g, '[当前]');
  translated = translated.replace(/\[Current\]/gi, '[当前]');
  translated = translated.replace(/\[CURRENT\]/g, '[当前]');

  return translated;
};

export const translateEnvText = (content: string): string => {
  if (!content) return '';
  const t = (key: string) => i18n.t(key);
  if (!isZh()) {
    return content;
  }

  let text = content;
  text = text.replace('[0:00] Status:', t('env.statusTime'));
  text = text.replace('--- Status ---', t('env.statusHeader'));
  text = text.replace('Current position:', t('env.currentPosition'));
  text = text.replace('Hunger level:', t('env.hungerLevel'));
  text = text.replace('Energy level:', t('env.energyLevel'));
  text = text.replace('Inventory:', t('env.inventory'));
  text = text.replace('Current time:', t('env.currentTime'));
  text = text.replace(/You are at\s*/g, t('env.youAreAt'));
  text = text.replace(/You arrived at\s*/g, t('env.youArrivedAt'));
  text = text.replace(/Nearby agents:/g, t('env.nearbyAgents'));
  text = text.replace(/plain\b/g, t('env.plain'));
  text = text.replace('[Message]', t('env.messageLabel'));
  return text;
};

export const prettifyAssistantContext = (content: string): string => {
  return prettifyAssistantCtx(content);
};
