export interface NetworkOverview {
  edgeCount: number;
  density: number;
  averageDegree: number;
  isolatedAgents: string[];
  componentCount: number;
  largestComponent: number;
  hubAgents: Array<{ id: string; degree: number }>;
}

const toAdjacency = (ids: string[], network: Record<string, string[]>) => {
  const adjacency = new globalThis.Map<string, Set<string>>();

  ids.forEach((id) => {
    adjacency.set(id, new Set(network[id] || []));
  });

  ids.forEach((id) => {
    const neighbors = adjacency.get(id)!;
    Array.from(neighbors).forEach((neighbor) => {
      if (!adjacency.has(neighbor)) {
        return;
      }
      adjacency.get(neighbor)!.add(id);
    });
  });

  return adjacency;
};

const countComponents = (adjacency: globalThis.Map<string, Set<string>>) => {
  const visited = new Set<string>();
  let componentCount = 0;
  let largestComponent = 0;

  adjacency.forEach((_, id) => {
    if (visited.has(id)) {
      return;
    }

    componentCount += 1;
    const queue = [id];
    visited.add(id);
    let size = 0;

    while (queue.length > 0) {
      const current = queue.shift()!;
      size += 1;
      adjacency.get(current)!.forEach((neighbor) => {
        if (visited.has(neighbor)) {
          return;
        }
        visited.add(neighbor);
        queue.push(neighbor);
      });
    }

    if (size > largestComponent) {
      largestComponent = size;
    }
  });

  return { componentCount, largestComponent };
};

export const buildNetworkOverview = (
  ids: string[],
  network: Record<string, string[]>,
): NetworkOverview => {
  const adjacency = toAdjacency(ids, network);
  const degrees = ids.map((id) => ({ id, degree: adjacency.get(id)!.size }));
  const edgeCount = degrees.reduce((sum, item) => sum + item.degree, 0) / 2;
  const possibleEdges = ids.length <= 1 ? 1 : (ids.length * (ids.length - 1)) / 2;
  const density = Math.min(1, edgeCount / possibleEdges);
  const isolatedAgents = degrees.filter((item) => item.degree === 0).map((item) => item.id);
  const averageDegree = ids.length > 0 ? (edgeCount * 2) / ids.length : 0;
  const { componentCount, largestComponent } = countComponents(adjacency);
  const hubAgents = [...degrees]
    .sort((left, right) => right.degree - left.degree || left.id.localeCompare(right.id))
    .slice(0, 4);

  return {
    edgeCount,
    density,
    averageDegree,
    isolatedAgents,
    componentCount,
    largestComponent,
    hubAgents,
  };
};
