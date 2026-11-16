import { apiClient } from '../../services/client';
import i18n from '../../i18n';
import type { Agent } from '../../types';

export const generateAgentsWithAI = async (
  count: number,
  description: string,
  providerId?: number | null,
  language?: string,
): Promise<Agent[]> => {
  const body: any = { count, description };
  if (providerId != null) {
    body.provider_id = providerId;
  }
  if (language) {
    body.language = language;
  }

  const response = await apiClient.post('/llm/generate_agents', body);
  const rawAgents: any[] = Array.isArray(response.data)
    ? response.data
    : Array.isArray(response.data?.agents)
      ? response.data.agents
      : [];

  const fallbackRole = i18n.t('agentGeneration.fallbacks.role');
  const fallbackProfile = i18n.t('agentGeneration.fallbacks.profile');

  return rawAgents.map((agent: any, index: number) => ({
    id: agent.id || `gen_${Date.now()}_${index}`,
    name: agent.name,
    role: agent.role || fallbackRole,
    avatarUrl: agent.avatarUrl || `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(agent.name || `agent_${index}`)}`,
    profile: agent.profile || fallbackProfile,
    llmConfig: { provider: agent.provider || 'backend', model: agent.model || 'default' },
    properties: agent.properties || {},
    history: agent.history || {},
    memory: agent.memory || [],
    knowledgeBase: agent.knowledgeBase || [],
  }));
};

export async function generateAgentsWithDemographics(
  totalAgents: number,
  demographics: { name: string; categories: string[] }[],
  archetypeProbabilities: Record<string, number>,
  traits: { name: string; mean: number; std: number }[],
  language: string,
  providerId?: string | number,
): Promise<Agent[]> {
  if (!traits || traits.length === 0) {
    throw new Error(i18n.t('agentGeneration.errors.traits_required'));
  }
  if (!demographics || demographics.length === 0) {
    throw new Error(i18n.t('agentGeneration.errors.demographics_required'));
  }
  for (const demographic of demographics) {
    if (!demographic.categories || demographic.categories.length === 0) {
      throw new Error(i18n.t('agentGeneration.errors.demographic_needs_categories',
        { name: demographic.name }));
    }
  }

  const response = await apiClient.post('/llm/generate_agents_demographics', {
    total_agents: totalAgents,
    demographics,
    archetype_probabilities: archetypeProbabilities,
    traits,
    language,
    provider_id: providerId != null ? Number(providerId) : undefined,
  });

  const rawAgents: any[] = Array.isArray(response.data)
    ? response.data
    : Array.isArray(response.data?.agents)
      ? response.data.agents
      : [];

  const fallbackRole = i18n.t('agentGeneration.fallbacks.role');
  const fallbackProfile = i18n.t('agentGeneration.fallbacks.profile');

  return rawAgents.map((agent: any, index: number) => ({
    id: agent.id || `gen_${Date.now()}_${index}`,
    name: agent.name,
    role: agent.role || fallbackRole,
    avatarUrl: agent.avatarUrl || `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(agent.name || `agent_${index}`)}`,
    profile: agent.profile || fallbackProfile,
    llmConfig: { provider: agent.provider || 'backend', model: agent.model || 'default' },
    properties: agent.properties || {},
    history: agent.history || {},
    memory: agent.memory || [],
    knowledgeBase: agent.knowledgeBase || [],
  }));
}
