/**
 * This file keeps the simple GAWorld starter presets in one place.
 *
 * - GAWORLD_PRESET_KEYS lists the starter choices the screen can show.
 * - getGAWorldPresetModes returns the city-system values for one starter choice.
 * - buildGAWorldInitialParams fills a new GAWorld setup with matching starter values.
 */

interface ScenarioParameterLike {
  key: string;
  default: unknown;
}

export const GAWORLD_PRESET_KEYS = ['fast', 'balanced', 'full_fidelity'] as const;

export type GAWorldPresetKey = typeof GAWORLD_PRESET_KEYS[number];

const GAWORLD_PRESET_MODES: Record<GAWorldPresetKey, Record<string, string>> = {
  fast: {
    information_mode: 'off',
    daily_life_mode: 'stable_routines',
    people_mode: 'simple_behavior',
    memory_mode: 'in_the_moment',
  },
  balanced: {
    information_mode: 'city_news',
    daily_life_mode: 'some_variation',
    people_mode: 'adaptive_behavior',
    memory_mode: 'some_continuity',
  },
  full_fidelity: {
    information_mode: 'active_flow',
    daily_life_mode: 'flexible_daily_life',
    people_mode: 'rich_human_behavior',
    memory_mode: 'rich_memory',
  },
};

function isPresetKey(value: unknown): value is GAWorldPresetKey {
  return typeof value === 'string' && GAWORLD_PRESET_KEYS.includes(value as GAWorldPresetKey);
}

export function getGAWorldPresetModes(presetKey: unknown): Record<string, string> {
  if (!isPresetKey(presetKey)) {
    return { ...GAWORLD_PRESET_MODES.fast };
  }
  return { ...GAWORLD_PRESET_MODES[presetKey] };
}

export function buildGAWorldInitialParams(
  parameters: ScenarioParameterLike[],
): Record<string, unknown> {
  const defaults: Record<string, unknown> = {};
  parameters.forEach((parameter) => {
    defaults[parameter.key] = parameter.default;
  });

  const executionProfile = isPresetKey(defaults.execution_profile)
    ? defaults.execution_profile
    : 'fast';

  return {
    ...defaults,
    execution_profile: executionProfile,
    ...getGAWorldPresetModes(executionProfile),
  };
}
