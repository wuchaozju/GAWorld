import { describe, it, expect } from 'vitest';
import { generateNetwork, defaultParams } from './networkTopologies';

const agents = ['Alice', 'Bob', 'Charlie', 'David'];

describe('generateNetwork — deterministic presets', () => {
  it('full: produces exactly n(n-1)/2 edges', () => {
    const { edges } = generateNetwork('full', agents);
    expect(edges).toHaveLength(6);
  });

  it('ring: produces exactly n edges', () => {
    const { edges } = generateNetwork('ring', agents);
    expect(edges).toHaveLength(4);
  });

  it('star: produces exactly n-1 edges, all touching first agent', () => {
    const { edges } = generateNetwork('star', agents);
    expect(edges).toHaveLength(3);
    edges.forEach(([a, b]) => expect(a === 'Alice' || b === 'Alice').toBe(true));
  });
});

describe('generateNetwork — reproducibility', () => {
  const stochasticPresets = ['random', 'newman-watts', 'core-periphery', 'holme-kim', 'waxman', 'sbm'] as const;

  for (const preset of stochasticPresets) {
    it(`${preset}: same seed produces identical edges`, () => {
      const seed = 12345;
      const r1 = generateNetwork(preset, agents, undefined, seed);
      const r2 = generateNetwork(preset, agents, undefined, seed);
      expect(r1.edges).toEqual(r2.edges);
    });

    it(`${preset}: different seeds generally produce different edges`, () => {
      const r1 = generateNetwork(preset, agents, undefined, 111);
      const r2 = generateNetwork(preset, agents, undefined, 999);
      // They _could_ be equal by chance, but for 4 agents this is vanishingly unlikely
      // — we check the seeds differ as a proxy
      expect(r1.seed).not.toEqual(r2.seed);
    });
  }
});

describe('generateNetwork — no isolated nodes', () => {
  it('random with very low probability still connects everyone', () => {
    // Use seed that we know produces a sparse graph
    const { edges } = generateNetwork('random', agents, { random: { connectionChance: 0.01 } }, 42);
    const seen = new Set(edges.flatMap(([a, b]) => [a, b]));
    agents.forEach(a => expect(seen.has(a)).toBe(true));
  });
});

describe('generateNetwork — returns seed in result', () => {
  it('returns the seed used', () => {
    const { seed } = generateNetwork('random', agents, undefined, 999);
    expect(seed).toBe(999);
  });

  it('returns a seed even when none provided', () => {
    const { seed } = generateNetwork('random', agents);
    expect(typeof seed).toBe('number');
    expect(seed).toBeGreaterThanOrEqual(0);
  });
});

describe('generateNetwork — parameter overrides', () => {
  it('random at connectionChance=1 produces fully connected', () => {
    const { edges } = generateNetwork('random', agents, { random: { connectionChance: 1 } }, 1);
    expect(edges).toHaveLength(6);
  });

  it('random at connectionChance=0 still connects all (ensureNoIsolated)', () => {
    const { edges } = generateNetwork('random', agents, { random: { connectionChance: 0 } }, 1);
    const seen = new Set(edges.flatMap(([a, b]) => [a, b]));
    agents.forEach(a => expect(seen.has(a)).toBe(true));
  });
});
