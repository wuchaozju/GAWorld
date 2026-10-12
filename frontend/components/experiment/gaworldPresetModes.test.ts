/**
 * This file checks the GAWorld starter preset helpers.
 *
 * - The first test checks that unknown preset names safely use the fast setup.
 * - The second test checks that initial params keep ordinary defaults and apply
 *   the selected city-system values.
 */

import { describe, expect, it } from 'vitest';
import { buildGAWorldInitialParams, getGAWorldPresetModes } from './gaworldPresetModes';

describe('gaworldPresetModes', () => {
  it('test_unknown_preset_uses_fast_city_modes', () => {
    expect(getGAWorldPresetModes('not-a-real-preset')).toEqual({
      information_mode: 'off',
      daily_life_mode: 'stable_routines',
      people_mode: 'simple_behavior',
      memory_mode: 'in_the_moment',
    });
  });

  it('test_initial_params_keep_defaults_and_apply_balanced_modes', () => {
    const params = buildGAWorldInitialParams([
      { key: 'execution_profile', default: 'balanced' },
      { key: 'seed', default: 123 },
      { key: 'agent_ids', default: '34,35' },
    ]);

    expect(params).toEqual({
      execution_profile: 'balanced',
      seed: 123,
      agent_ids: '34,35',
      information_mode: 'city_news',
      daily_life_mode: 'some_variation',
      people_mode: 'adaptive_behavior',
      memory_mode: 'some_continuity',
    });
  });
});
