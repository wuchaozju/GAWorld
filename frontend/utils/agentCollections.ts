import type { ManualAgentType } from "../store/experiment-builder";

export interface AgentCollection {
  key: string;
  title: string;
  representative: ManualAgentType;
  members: ManualAgentType[];
  count: number;
  tier: string;
  providerId: number | null;
  propertyCount: number;
}

const normalizeLabel = (label: string) => String(label || "").replace(/\s+\d+$/, "").trim();

const serializeProperties = (properties: Record<string, unknown>) =>
  Object.entries(properties || {})
    .filter(([key]) => key !== "avatarUrl")
    .sort(([left], [right]) => left.localeCompare(right, undefined, { sensitivity: "base" }))
    .map(([key, value]) => `${key}:${String(value ?? "")}`)
    .join("|");

export const buildAgentCollections = (
  agentTypes: ManualAgentType[],
  resolveTier: (agent: ManualAgentType) => string,
): AgentCollection[] => {
  const groups = new globalThis.Map<string, AgentCollection>();

  agentTypes.forEach((agent) => {
    const tier = resolveTier(agent);
    const title = normalizeLabel(agent.label) || agent.label;
    const key = [
      title,
      agent.rolePrompt || "",
      agent.userProfile || "",
      String(agent.providerId ?? ""),
      tier,
      serializeProperties(agent.properties || {}),
    ].join("::");

    const current = groups.get(key);
    if (current) {
      current.members.push(agent);
      current.count += Math.max(1, agent.count || 1);
      return;
    }

    groups.set(key, {
      key,
      title,
      representative: agent,
      members: [agent],
      count: Math.max(1, agent.count || 1),
      tier,
      providerId: agent.providerId ?? null,
      propertyCount: Object.keys(agent.properties || {}).filter((item) => item !== "avatarUrl").length,
    });
  });

  return Array.from(groups.values()).sort((left, right) => {
    if (left.count !== right.count) {
      return right.count - left.count;
    }

    return left.title.localeCompare(right.title, undefined, { sensitivity: "base" });
  });
};
