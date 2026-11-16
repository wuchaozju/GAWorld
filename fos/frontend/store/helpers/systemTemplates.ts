import type { Agent, LLMConfig, SimulationTemplate } from '../../types';
import { DEFAULT_TIME_CONFIG } from './time';

const generateNormDisruptionAgents = (defaultModel: LLMConfig): Agent[] => {
  const professions = ['教师', '商人', '医生', '警察', '农民', '工人', '管理员', '艺术家', '记者', '律师'];
  const personalities = ['保守', '开放', '理性', '感性', '叛逆', '顺从', '社交', '内向', '乐观', '悲观'];

  return Array.from({ length: 20 }).map((_, index) => {
    const profession = professions[index % professions.length];
    const personality = personalities[index % personalities.length];
    return {
      id: `norm_${index + 1}`,
      name: `${profession}${String.fromCharCode(65 + (index % 20))}`,
      role: profession,
      avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=norm${index}`,
      profile: `${profession}，性格${personality}。在面对新规范时倾向于${personality === '保守' ? '谨慎遵守' : personality === '叛逆' ? '主动反抗' : '观察他人'}。`,
      llmConfig: defaultModel,
      properties: {
        规范遵守度: 50 + Math.floor(Math.random() * 40),
        社会地位: 30 + Math.floor(Math.random() * 50),
        反抗倾向: 20 + Math.floor(Math.random() * 60),
      },
      history: {},
      memory: [],
      knowledgeBase: [],
    };
  });
};

const generatePolicyDiffusionAgents = (defaultModel: LLMConfig): Agent[] => {
  return [
    ...Array.from({ length: 3 }).map((_, index) => ({
      id: `policy_top_${index + 1}`,
      name: `政策官员${index + 1}`,
      role: '政策制定者',
      avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=policy_top${index}`,
      profile: '政府部门的高级官员，负责制定宏观政策。相信政策是科学合理的，但往往忽视基层现实。',
      llmConfig: defaultModel,
      properties: { 官级: 90, 意识形态强度: 80, 现实理解度: 30 },
      history: {},
      memory: [],
      knowledgeBase: [],
    })),
    ...Array.from({ length: 7 }).map((_, index) => ({
      id: `policy_mid_${index + 1}`,
      name: `社区主管${index + 1}`,
      role: '中层执行官',
      avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=policy_mid${index}`,
      profile: '社区管理者，处于上下级之间的压力。既要向上级交代，也要应对基层的现实困难。',
      llmConfig: defaultModel,
      properties: { 官级: 50, 灵活性: 60 + Math.floor(Math.random() * 30), 个人利益驱动: 40 },
      history: {},
      memory: [],
      knowledgeBase: [],
    })),
    ...Array.from({ length: 10 }).map((_, index) => ({
      id: `policy_base_${index + 1}`,
      name: `居民${index + 1}`,
      role: '基层接收者',
      avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=policy_base${index}`,
      profile: '普通居民，直接受政策影响。更关心实际利益而非理想主义。',
      llmConfig: defaultModel,
      properties: { 官级: 10, 实用性: 80, 对官僚的不信任度: 50 + Math.floor(Math.random() * 40) },
      history: {},
      memory: [],
      knowledgeBase: [],
    })),
  ];
};

const generatePolarizationAgents = (defaultModel: LLMConfig): Agent[] => {
  return [
    ...Array.from({ length: 8 }).map((_, index) => ({
      id: `polar_radical_${index + 1}`,
      name: `激进者${index + 1}`,
      role: '激进派',
      avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=radical${index}`,
      profile: '信念坚定，对立场敏感。容易被同立场的内容激怒。',
      llmConfig: defaultModel,
      properties: {
        立场强度: 85 + Math.floor(Math.random() * 15),
        情绪易激怒度: 70 + Math.floor(Math.random() * 25),
        包容度: 20 + Math.floor(Math.random() * 20),
        接收度: 0,
      },
      history: {},
      memory: [],
      knowledgeBase: [],
    })),
    ...Array.from({ length: 8 }).map((_, index) => ({
      id: `polar_conservative_${index + 1}`,
      name: `保守者${index + 1}`,
      role: '保守派',
      avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=conservative${index}`,
      profile: '立场传统，对变化持谨慎态度。',
      llmConfig: defaultModel,
      properties: {
        立场强度: 75 + Math.floor(Math.random() * 20),
        情绪易激怒度: 60 + Math.floor(Math.random() * 30),
        包容度: 30 + Math.floor(Math.random() * 20),
        接收度: 100,
      },
      history: {},
      memory: [],
      knowledgeBase: [],
    })),
    ...Array.from({ length: 4 }).map((_, index) => ({
      id: `polar_neutral_${index + 1}`,
      name: `中立者${index + 1}`,
      role: '中立派',
      avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=neutral${index}`,
      profile: '倾向于平衡考虑，但容易受信息流影响。',
      llmConfig: defaultModel,
      properties: {
        立场强度: 30 + Math.floor(Math.random() * 30),
        情绪易激怒度: 40 + Math.floor(Math.random() * 30),
        包容度: 60 + Math.floor(Math.random() * 30),
        接收度: 50,
      },
      history: {},
      memory: [],
      knowledgeBase: [],
    })),
  ];
};

const generateResourceScarcityAgents = (defaultModel: LLMConfig): Agent[] => {
  const roles = ['医生', '军人', '商贩', '教师', '工程师', '农民', '老人', '儿童监护人', '牧师', '黑市商人'];

  return Array.from({ length: 20 }).map((_, index) => {
    const role = roles[index % roles.length];
    const trustLevel = index % 3 === 0 ? 80 : index % 3 === 1 ? 50 : 20;
    return {
      id: `scarcity_${index + 1}`,
      name: `${role}${String.fromCharCode(65 + (index % 20))}`,
      role,
      avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=scarcity${index}`,
      profile: `${role}。在灾难中${trustLevel > 70 ? '因为职业受信任' : trustLevel > 40 ? '信用中等' : '信用低下或被怀疑'}。`,
      llmConfig: defaultModel,
      properties: {
        社会资本: trustLevel + Math.floor(Math.random() * 20 - 10),
        诚实度: 50 + Math.floor(Math.random() * 50),
        绝望指数: 50 + Math.floor(Math.random() * 40),
        资源占有: 10 + Math.floor(Math.random() * 30),
        欺诈倾向: 100 - trustLevel + Math.floor(Math.random() * 30),
      },
      history: {},
      memory: [],
      knowledgeBase: [],
    };
  });
};

export const SYSTEM_TEMPLATES: SimulationTemplate[] = [
  {
    id: 'norm_disruption',
    name: '社会规范的突变',
    description: '常人方法论视角：20个异质代理在突发规范变化中的意义构建与适应。观察从服从→反抗→黑市协议的演化轨迹。',
    category: 'system',
    sceneType: 'village',
    agents: generateNormDisruptionAgents({ provider: 'OpenAI', model: 'gpt-4o' }),
    defaultTimeConfig: DEFAULT_TIME_CONFIG,
  },
  {
    id: 'policy_diffusion',
    name: '政策传播中的意义磨损',
    description: '街头官僚制视角：模拟三层级组织(政府→社区→居民)中政策的重构与异化。验证底层逻辑如何消解宏观规划。',
    category: 'system',
    sceneType: 'policy_cascade_scene',
    agents: generatePolicyDiffusionAgents({ provider: 'OpenAI', model: 'gpt-4o' }),
    defaultTimeConfig: DEFAULT_TIME_CONFIG,
  },
  {
    id: 'polarization',
    name: '极化与数字茧房生成',
    description: '回声壁效应视角：20个代理（8激进+8保守+4中立）在推荐算法驱动下的观点极化与群体分裂。追踪情绪传染机制。',
    category: 'system',
    sceneType: 'village',
    agents: generatePolarizationAgents({ provider: 'OpenAI', model: 'gpt-4o' }),
    defaultTimeConfig: DEFAULT_TIME_CONFIG,
  },
  {
    id: 'resource_scarcity',
    name: '稀缺资源下的社会契约',
    description: '霍布斯丛林视角：灾后社区中，拥有社会资本的代理能否通过信用契约度过危机，还是陷入大规模欺诈与崩溃？',
    category: 'system',
    sceneType: 'village',
    agents: generateResourceScarcityAgents({ provider: 'OpenAI', model: 'gpt-4o' }),
    defaultTimeConfig: DEFAULT_TIME_CONFIG,
  },
  {
    id: 'village',
    name: '乡村治理',
    description: '适用于乡村治理的标准预设场景。',
    category: 'system',
    sceneType: 'village',
    agents: [],
    defaultTimeConfig: {
      baseTime: new Date().toISOString(),
      unit: 'day',
      step: 1,
    },
  },
  {
    id: 'council',
    name: '议事会',
    description: '5人议会决策模拟。',
    category: 'system',
    sceneType: 'council',
    agents: [],
    defaultTimeConfig: {
      baseTime: new Date().toISOString(),
      unit: 'hour',
      step: 2,
    },
  },
  // NOTE: Werewolf template removed from active templates.
  // Scenario is unsupported/inactive — requires dedicated role/phase runtime.
  // Template definition kept in git history for future re-enablement.
];

// Filter: only expose supported templates (exclude any future unsupported ones)
export const SUPPORTED_SYSTEM_TEMPLATES = SYSTEM_TEMPLATES;
