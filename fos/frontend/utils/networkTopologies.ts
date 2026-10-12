/**
 * Network topology generation utilities.
 *
 * All stochastic presets use a seeded mulberry32 PRNG so that the same
 * seed + preset + params always produces the same network. The seed is
 * returned in NetworkResult and should be stored alongside the edge list.
 *
 * Exports: generateNetwork, defaultParams, PresetType, NetworkResult, PresetParams
 */

export type PresetType =
  | 'full' | 'random' | 'ring' | 'star'
  | 'newman-watts' | 'core-periphery' | 'holme-kim' | 'waxman' | 'sbm'
  | 'custom';

export interface NetworkResult {
  edges: [string, string][];
  preset: PresetType;
  seed: number;
}

export interface PresetParams {
  random: { connectionChance: number };
  'newman-watts': { neighborsEachSide: number; shortcutChance: number };
  'core-periphery': {
    influencerPercent: number;
    influencerConnectivity: number;
    influencerReach: number;
    regularConnectivity: number;
  };
  'holme-kim': { newConnections: number; clusteringChance: number };
  waxman: { maxDistance: number; distanceEffect: number };
  sbm: { groupSize: number; withinGroupConnectivity: number; bridgeConnections: number };
}

export const defaultParams: PresetParams = {
  random: { connectionChance: 0.3 },
  'newman-watts': { neighborsEachSide: 2, shortcutChance: 0.1 },
  'core-periphery': {
    influencerPercent: 0.2,
    influencerConnectivity: 0.8,
    influencerReach: 0.4,
    regularConnectivity: 0.1,
  },
  'holme-kim': { newConnections: 3, clusteringChance: 0.5 },
  waxman: { maxDistance: 0.5, distanceEffect: 0.5 },
  sbm: { groupSize: 5, withinGroupConnectivity: 0.6, bridgeConnections: 1 },
};

/**
 * mulberry32 seeded PRNG.
 * Returns a function that produces uniformly distributed floats in [0, 1).
 * Same seed always produces the same sequence.
 */
function makePrng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s += 0x6D2B79F5;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Ensures no agent is isolated (has zero connections).
 * Uses the provided rng — never Math.random().
 */
function ensureNoIsolatedNodes(
  edges: [string, string][],
  agentNames: string[],
  rng: () => number,
): [string, string][] {
  if (agentNames.length <= 1) return edges;

  const connectionCount = new Map<string, number>();
  agentNames.forEach(name => connectionCount.set(name, 0));

  edges.forEach(([a, b]) => {
    connectionCount.set(a, (connectionCount.get(a) ?? 0) + 1);
    connectionCount.set(b, (connectionCount.get(b) ?? 0) + 1);
  });

  const result = [...edges];

  for (const agent of agentNames) {
    if ((connectionCount.get(agent) ?? 0) === 0) {
      const others = agentNames.filter(id => id !== agent);
      const neighbor = others[Math.floor(rng() * others.length)];
      result.push([agent, neighbor]);
    }
  }

  return result;
}

/**
 * Generates a network topology based on the selected preset.
 *
 * @param preset  - Which topology to generate
 * @param agentNames - Ordered list of agent names
 * @param params  - Optional overrides for preset parameters
 * @param seed    - Optional seed for reproducibility. If omitted, a random seed
 *                  is chosen. Either way, the seed used is returned in the result.
 */
export function generateNetwork(
  preset: PresetType,
  agentNames: string[],
  params?: Partial<PresetParams>,
  seed?: number,
): NetworkResult {
  const usedSeed = seed ?? Math.floor(Math.random() * 2 ** 32);
  const rng = makePrng(usedSeed);

  const n = agentNames.length;
  const edges: [string, string][] = [];
  const p = { ...defaultParams, ...params } as PresetParams;

  const addEdge = (a: string, b: string) => edges.push([a, b]);

  if (preset === 'full') {
    for (let i = 0; i < n; i++)
      for (let j = i + 1; j < n; j++)
        addEdge(agentNames[i], agentNames[j]);

  } else if (preset === 'ring') {
    for (let i = 0; i < n; i++)
      addEdge(agentNames[i], agentNames[(i + 1) % n]);

  } else if (preset === 'star') {
    if (n > 1)
      for (let i = 1; i < n; i++)
        addEdge(agentNames[0], agentNames[i]);

  } else if (preset === 'random') {
    const { connectionChance } = p.random;
    for (let i = 0; i < n; i++)
      for (let j = i + 1; j < n; j++)
        if (rng() < connectionChance)
          addEdge(agentNames[i], agentNames[j]);

  } else if (preset === 'newman-watts') {
    const { neighborsEachSide, shortcutChance } = p['newman-watts'];
    const k = Math.min(neighborsEachSide, Math.floor((n - 1) / 2));

    for (let i = 0; i < n; i++)
      for (let offset = 1; offset <= k; offset++)
        addEdge(agentNames[i], agentNames[(i + offset) % n]);

    for (let i = 0; i < n; i++) {
      for (let offset = k + 1; offset <= Math.floor(n / 2); offset++) {
        if (rng() < shortcutChance) {
          const neighborIdx = (i + offset) % n;
          const edge: [string, string] = [agentNames[i], agentNames[neighborIdx]];
          const exists = edges.some(([a, b]) =>
            (a === edge[0] && b === edge[1]) || (a === edge[1] && b === edge[0])
          );
          if (!exists) addEdge(edge[0], edge[1]);
        }
      }
    }

  } else if (preset === 'core-periphery') {
    const { influencerPercent, influencerConnectivity, influencerReach, regularConnectivity } =
      p['core-periphery'];
    const coreSize = Math.max(2, Math.floor(n * influencerPercent));
    const isCore = (idx: number) => idx < coreSize;

    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const prob = isCore(i) && isCore(j) ? influencerConnectivity
          : isCore(i) || isCore(j) ? influencerReach
          : regularConnectivity;
        if (rng() < prob) addEdge(agentNames[i], agentNames[j]);
      }
    }

  } else if (preset === 'holme-kim') {
    const { newConnections, clusteringChance } = p['holme-kim'];
    const mClamped = Math.min(newConnections, n - 1);
    const adjacency = new Map<string, Set<string>>();
    agentNames.forEach(name => adjacency.set(name, new Set()));

    const addAdjEdge = (a: string, b: string) => {
      adjacency.get(a)!.add(b);
      adjacency.get(b)!.add(a);
      addEdge(a, b);
    };

    const seedSize = mClamped + 1;
    for (let i = 0; i < seedSize; i++)
      for (let j = i + 1; j < seedSize; j++)
        addAdjEdge(agentNames[i], agentNames[j]);

    for (let i = seedSize; i < n; i++) {
      const newNode = agentNames[i];
      const connected = new Set<string>();
      let totalDegree = 0;
      for (let j = 0; j < i; j++) totalDegree += adjacency.get(agentNames[j])!.size;

      let r = rng() * totalDegree;
      let firstTarget = agentNames[0];
      for (let j = 0; j < i; j++) {
        r -= adjacency.get(agentNames[j])!.size;
        if (r <= 0) { firstTarget = agentNames[j]; break; }
      }
      addAdjEdge(newNode, firstTarget);
      connected.add(firstTarget);

      while (connected.size < mClamped && connected.size < i) {
        if (rng() < clusteringChance) {
          const lastConnected = Array.from(connected).pop()!;
          const neighbors = Array.from(adjacency.get(lastConnected)!).filter(
            nb => !connected.has(nb) && nb !== newNode
          );
          if (neighbors.length > 0) {
            const triadTarget = neighbors[Math.floor(rng() * neighbors.length)];
            addAdjEdge(newNode, triadTarget);
            connected.add(triadTarget);
            continue;
          }
        }
        r = rng() * totalDegree;
        for (let j = 0; j < i; j++) {
          if (connected.has(agentNames[j])) continue;
          r -= adjacency.get(agentNames[j])!.size;
          if (r <= 0) {
            addAdjEdge(newNode, agentNames[j]);
            connected.add(agentNames[j]);
            break;
          }
        }
      }
    }

  } else if (preset === 'waxman') {
    const { maxDistance, distanceEffect } = p.waxman;
    const positions: Record<string, { x: number; y: number }> = {};
    agentNames.forEach(id => { positions[id] = { x: rng(), y: rng() }; });
    const maxDist = Math.sqrt(2);

    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const id1 = agentNames[i], id2 = agentNames[j];
        const dx = positions[id1].x - positions[id2].x;
        const dy = positions[id1].y - positions[id2].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const prob = distanceEffect * Math.exp(-dist / (maxDistance * maxDist));
        if (rng() < prob) addEdge(id1, id2);
      }
    }

  } else if (preset === 'sbm') {
    const { groupSize, withinGroupConnectivity, bridgeConnections } = p.sbm;
    const groupSizeClamped = Math.max(1, Math.round(groupSize));
    const pBetween = Math.min(1, bridgeConnections / Math.max(1, n - groupSizeClamped));

    const groups: string[][] = [];
    for (let i = 0; i < n; i += groupSizeClamped)
      groups.push(agentNames.slice(i, i + groupSizeClamped));

    for (const group of groups)
      for (let i = 0; i < group.length; i++)
        for (let j = i + 1; j < group.length; j++)
          if (rng() < withinGroupConnectivity)
            addEdge(group[i], group[j]);

    for (let g1 = 0; g1 < groups.length; g1++)
      for (let g2 = g1 + 1; g2 < groups.length; g2++)
        for (const a of groups[g1])
          for (const b of groups[g2])
            if (rng() < pBetween)
              addEdge(a, b);
  }

  const connectedEdges = preset === 'full' || preset === 'ring' || preset === 'star'
    ? edges  // deterministic presets are guaranteed connected by construction
    : ensureNoIsolatedNodes(edges, agentNames, rng);

  return { edges: connectedEdges, preset, seed: usedSeed };
}
