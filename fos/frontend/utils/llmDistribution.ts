export interface LLMAllocation {
  providerId: number;
  providerName: string;
  modelName: string;
  percentage: number;
}

type LLMDefaultConfig = { provider: string; model: string; provider_id?: number | null };

type DistributableAgent = {
  id: string;
  name: string;
  llmConfig?: { provider: string; model: string };
  provider_id?: number;
  properties?: Record<string, unknown>;
};

function createSeededRng(seed: string): () => number {
  let h = 0xdeadbeef;
  for (let i = 0; i < seed.length; i += 1) {
    h = Math.imul(h ^ seed.charCodeAt(i), 2654435761);
  }
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2654435761);
    h = Math.imul(h ^ (h >>> 16), 2654435761);
    return (h >>> 0) / 4294967296;
  };
}

export function applyLlmDistribution<T extends DistributableAgent>(
  agents: T[],
  allocations: LLMAllocation[],
  seed: string,
  defaultConfig: LLMDefaultConfig,
): T[] {
  if (allocations.length === 0) {
    return agents.map((agent) => ({
      ...agent,
      llmConfig: {
        provider: defaultConfig.provider,
        model: defaultConfig.model,
      },
      provider_id: defaultConfig.provider_id ?? agent.provider_id,
      properties: {
        ...agent.properties,
        provider_id: defaultConfig.provider_id ?? agent.provider_id ?? agent.properties?.provider_id,
      },
    }));
  }

  const total = allocations.reduce((sum, allocation) => sum + allocation.percentage, 0);
  if (total !== 100) {
    throw new Error('LLM allocations must sum to 100%');
  }

  const agentCount = agents.length;
  const entries = allocations.map((allocation, index) => {
    const exact = (allocation.percentage / 100) * agentCount;
    const floor = Math.floor(exact);
    return {
      allocation,
      count: floor,
      remainder: exact - floor,
      originalIndex: index,
    };
  });

  const assigned = entries.reduce((sum, entry) => sum + entry.count, 0);
  const leftover = agentCount - assigned;

  const sorted = [...entries].sort(
    (a, b) => b.remainder - a.remainder || a.originalIndex - b.originalIndex,
  );

  for (let i = 0; i < leftover; i += 1) {
    sorted[i].count += 1;
  }

  const llmAssignments: LLMAllocation[] = [];
  for (const entry of sorted) {
    for (let i = 0; i < entry.count; i += 1) {
      llmAssignments.push(entry.allocation);
    }
  }

  const rng = createSeededRng(seed);
  for (let i = llmAssignments.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rng() * (i + 1));
    [llmAssignments[i], llmAssignments[j]] = [llmAssignments[j], llmAssignments[i]];
  }

  return agents.map((agent, index) => {
    const assignment = llmAssignments[index] || allocations[allocations.length - 1];
    return {
      ...agent,
      llmConfig: {
        provider: assignment.providerName,
        model: assignment.modelName,
      },
      provider_id: assignment.providerId,
      properties: {
        ...agent.properties,
        provider_id: assignment.providerId,
      },
    };
  });
}