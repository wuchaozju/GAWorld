/**
 * Checks that each scenario routes to the correct scene type.
 *
 * Policy Meaning Erosion has dedicated cascade runtime semantics. It must
 * route to policy_cascade_scene so it does not fall back to the generic
 * experiment engine.
 */

import { describe, expect, it } from 'vitest';
import { isPolicyCascadeScenarioId } from '../../utils/policyCascade';

// This reimplements the logic from ExperimentBuilderModal.tsx lines 132-154
function resolveSceneType(
  id: string | undefined,
  name: string | undefined,
  category: string | undefined,
): string {
  const isPolicyCascade = isPolicyCascadeScenarioId(id);

  const isNewArchitecture = category === 'game_theory' ||
    category === 'discussion' ||
    category === 'grid' ||
    category === 'sociology' ||
    category === 'social_deduction' ||
    category === 'spatial' ||
    category === 'generative_city' ||
    category === 'custom';

  return isPolicyCascade ? 'policy_cascade_scene' : isNewArchitecture ? 'experiment' : 'generic';
}

describe('scene type routing', () => {
  it('routes policy_erosion to policy_cascade_scene', () => {
    const result = resolveSceneType('policy_erosion', 'Policy Meaning Erosion', 'sociology');
    expect(result).toBe('policy_cascade_scene');
  });

  it('routes policy_diffusion to policy_cascade_scene (still legacy)', () => {
    const result = resolveSceneType('policy_diffusion', 'Policy Diffusion', 'sociology');
    expect(result).toBe('policy_cascade_scene');
  });

  it('routes policyDiffusion to policy_cascade_scene (capitalized ID)', () => {
    const result = resolveSceneType('policyDiffusion', 'Policy Diffusion', 'sociology');
    expect(result).toBe('policy_cascade_scene');
  });

  it('does not match unknown scenarios by name containing "policy"', () => {
    const result = resolveSceneType('some_other', 'Some Policy Scenario', 'sociology');
    expect(result).toBe('experiment');
  });

  it('routes non-new-architecture scenarios to generic', () => {
    const result = resolveSceneType('village', 'Village Life', 'roleplay');
    expect(result).toBe('generic');
  });

  it('routes custom category scenarios to experiment', () => {
    const result = resolveSceneType('custom_scenario', 'Custom', 'custom');
    expect(result).toBe('experiment');
  });

  it('routes scenarios without a category to generic', () => {
    const result = resolveSceneType('test', 'Test', undefined);
    expect(result).toBe('generic');
  });
});
