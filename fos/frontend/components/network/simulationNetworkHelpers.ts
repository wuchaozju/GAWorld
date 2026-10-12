/**
 * This file holds the small network-building helpers for the simulation
 * network panel.
 *
 * The helpers here build empty networks, copy a network safely, connect
 * or remove pairs, keep everyone connected, and generate preset shapes.
 */

import {
  Grid3X3,
  Layers,
  RefreshCw,
  Share2,
  Shuffle,
  Users,
} from "lucide-react";
import type { ElementType } from "react";

import type { SocialNetwork } from "../../types";

export type SimulationPresetType =
  | "full"
  | "random"
  | "ring"
  | "star"
  | "newman-watts"
  | "core-periphery"
  | "holme-kim"
  | "waxman"
  | "sbm";

export interface NewmanWattsParams {
  neighborsEachSide: number;
  shortcutChance: number;
}

export interface RandomParams {
  connectionChance: number;
}

export const simulationPresetIcons: Record<
  SimulationPresetType,
  { icon: ElementType; translationKey: string }
> = {
  full: { icon: Share2, translationKey: "fully_connected" },
  random: { icon: Shuffle, translationKey: "random" },
  ring: { icon: RefreshCw, translationKey: "ring" },
  star: { icon: Users, translationKey: "star" },
  "newman-watts": { icon: Grid3X3, translationKey: "small_world" },
  "core-periphery": { icon: Layers, translationKey: "core_periphery" },
  "holme-kim": { icon: Share2, translationKey: "scale_free" },
  waxman: { icon: Grid3X3, translationKey: "spatial" },
  sbm: { icon: Users, translationKey: "communities" },
};

export const createEmptyNetwork = (agentNames: string[]): SocialNetwork => {
  const next: SocialNetwork = {};
  agentNames.forEach((name) => {
    next[name] = [];
  });
  return next;
};

export const cloneNetwork = (
  network: SocialNetwork,
  agentNames: string[]
): SocialNetwork => {
  const next = createEmptyNetwork(agentNames);
  agentNames.forEach((name) => {
    next[name] = [...(network[name] || [])].filter((target) =>
      agentNames.includes(target)
    );
  });
  return next;
};

export const connectPair = (
  network: SocialNetwork,
  source: string,
  target: string
): void => {
  if (source === target) return;
  if (!network[source].includes(target)) {
    network[source].push(target);
  }
  if (!network[target].includes(source)) {
    network[target].push(source);
  }
};

export const removePair = (
  network: SocialNetwork,
  source: string,
  target: string
): void => {
  network[source] = network[source].filter((value) => value !== target);
  network[target] = network[target].filter((value) => value !== source);
};

export const ensureNoIsolatedNodes = (
  network: SocialNetwork,
  agentNames: string[]
): SocialNetwork => {
  if (agentNames.length <= 1) return network;

  const next = cloneNetwork(network, agentNames);
  agentNames.forEach((name, index) => {
    if (next[name].length > 0) return;
    const neighbor = agentNames[(index + 1) % agentNames.length];
    connectPair(next, name, neighbor);
  });
  return next;
};

export const buildPresetNetwork = (
  preset: SimulationPresetType,
  agentNames: string[],
  randomParams: RandomParams,
  newmanWattsParams: NewmanWattsParams
): SocialNetwork => {
  const count = agentNames.length;
  const next = createEmptyNetwork(agentNames);

  if (preset === "full") {
    for (let i = 0; i < count; i += 1) {
      for (let j = i + 1; j < count; j += 1) {
        connectPair(next, agentNames[i], agentNames[j]);
      }
    }
    return next;
  }

  if (preset === "ring") {
    for (let i = 0; i < count; i += 1) {
      connectPair(next, agentNames[i], agentNames[(i + 1) % count]);
    }
    return next;
  }

  if (preset === "star") {
    for (let i = 1; i < count; i += 1) {
      connectPair(next, agentNames[0], agentNames[i]);
    }
    return next;
  }

  if (preset === "random") {
    for (let i = 0; i < count; i += 1) {
      for (let j = i + 1; j < count; j += 1) {
        if (Math.random() < randomParams.connectionChance) {
          connectPair(next, agentNames[i], agentNames[j]);
        }
      }
    }
    return ensureNoIsolatedNodes(next, agentNames);
  }

  if (preset === "newman-watts") {
    const maxNeighbors = Math.max(
      1,
      Math.min(newmanWattsParams.neighborsEachSide, Math.floor((count - 1) / 2))
    );
    for (let i = 0; i < count; i += 1) {
      for (let offset = 1; offset <= maxNeighbors; offset += 1) {
        connectPair(next, agentNames[i], agentNames[(i + offset) % count]);
      }
    }

    for (let i = 0; i < count; i += 1) {
      for (let offset = maxNeighbors + 1; offset <= Math.floor(count / 2); offset += 1) {
        if (Math.random() < newmanWattsParams.shortcutChance) {
          connectPair(next, agentNames[i], agentNames[(i + offset) % count]);
        }
      }
    }
    return ensureNoIsolatedNodes(next, agentNames);
  }

  if (preset === "core-periphery") {
    const coreSize = Math.max(2, Math.floor(count * 0.2));
    const isCore = (index: number): boolean => index < coreSize;
    for (let i = 0; i < count; i += 1) {
      for (let j = i + 1; j < count; j += 1) {
        const probability = isCore(i) && isCore(j) ? 0.8 : isCore(i) || isCore(j) ? 0.4 : 0.1;
        if (Math.random() < probability) {
          connectPair(next, agentNames[i], agentNames[j]);
        }
      }
    }
    return ensureNoIsolatedNodes(next, agentNames);
  }

  if (preset === "holme-kim") {
    const newConnections = Math.min(3, Math.max(1, count - 1));
    const seedSize = Math.min(count, newConnections + 1);
    for (let i = 0; i < seedSize; i += 1) {
      for (let j = i + 1; j < seedSize; j += 1) {
        connectPair(next, agentNames[i], agentNames[j]);
      }
    }

    for (let i = seedSize; i < count; i += 1) {
      const newNode = agentNames[i];
      const connected = new Set<string>();
      let totalDegree = 0;
      for (let j = 0; j < i; j += 1) {
        totalDegree += next[agentNames[j]].length;
      }
      totalDegree = Math.max(totalDegree, 1);

      let roll = Math.random() * totalDegree;
      let firstTarget = agentNames[0];
      for (let j = 0; j < i; j += 1) {
        roll -= next[agentNames[j]].length;
        if (roll <= 0) {
          firstTarget = agentNames[j];
          break;
        }
      }

      connectPair(next, newNode, firstTarget);
      connected.add(firstTarget);

      while (connected.size < newConnections && connected.size < i) {
        const lastConnected = Array.from(connected).at(-1);
        const triadOptions = lastConnected
          ? next[lastConnected].filter(
              (neighbor) => neighbor !== newNode && !connected.has(neighbor)
            )
          : [];
        if (triadOptions.length > 0 && Math.random() < 0.5) {
          const triadTarget =
            triadOptions[Math.floor(Math.random() * triadOptions.length)];
          connectPair(next, newNode, triadTarget);
          connected.add(triadTarget);
          continue;
        }

        let fallbackRoll = Math.random() * totalDegree;
        for (let j = 0; j < i; j += 1) {
          if (connected.has(agentNames[j])) continue;
          fallbackRoll -= next[agentNames[j]].length;
          if (fallbackRoll <= 0) {
            connectPair(next, newNode, agentNames[j]);
            connected.add(agentNames[j]);
            break;
          }
        }
      }
    }
    return ensureNoIsolatedNodes(next, agentNames);
  }

  if (preset === "waxman") {
    const positions: Record<string, { x: number; y: number }> = {};
    agentNames.forEach((name) => {
      positions[name] = { x: Math.random(), y: Math.random() };
    });
    const maxDistance = Math.sqrt(2);

    for (let i = 0; i < count; i += 1) {
      for (let j = i + 1; j < count; j += 1) {
        const left = positions[agentNames[i]];
        const right = positions[agentNames[j]];
        const dx = left.x - right.x;
        const dy = left.y - right.y;
        const distance = Math.sqrt(dx * dx + dy * dy);
        const probability = 0.5 * Math.exp(-distance / (0.5 * maxDistance));
        if (Math.random() < probability) {
          connectPair(next, agentNames[i], agentNames[j]);
        }
      }
    }
    return ensureNoIsolatedNodes(next, agentNames);
  }

  if (preset === "sbm") {
    const groupSize = Math.max(1, Math.round(Math.sqrt(count)));
    const groupByAgent: Record<string, number> = {};
    agentNames.forEach((name, index) => {
      groupByAgent[name] = Math.floor(index / groupSize);
    });

    for (let i = 0; i < count; i += 1) {
      for (let j = i + 1; j < count; j += 1) {
        const sameGroup =
          groupByAgent[agentNames[i]] === groupByAgent[agentNames[j]];
        const probability = sameGroup ? 0.6 : 0.15;
        if (Math.random() < probability) {
          connectPair(next, agentNames[i], agentNames[j]);
        }
      }
    }
    return ensureNoIsolatedNodes(next, agentNames);
  }

  return buildPresetNetwork("full", agentNames, randomParams, newmanWattsParams);
};
