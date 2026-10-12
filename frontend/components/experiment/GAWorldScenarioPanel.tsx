/**
 * This file shows the beginner-friendly GAWorld setup panel.
 *
 * - GAWorldScenarioPanel shows starter presets, city-system groups, and an
 *   advanced section for the seed.
 * - applyPreset updates the visible city-system settings from one starter mode.
 * - updateMode changes one city-system choice while keeping the rest.
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { GAWORLD_PRESET_KEYS, getGAWorldPresetModes, type GAWorldPresetKey } from './gaworldPresetModes';

interface GAWorldScenarioPanelProps {
  scenarioParams: Record<string, unknown>;
  setScenarioParams: (params: Record<string, unknown>) => void;
}

interface PresetOption {
  key: GAWorldPresetKey;
  modes: Record<string, string>;
}

interface ModeOption {
  key: string;
  titleKey: string;
  fallbackTitle: string;
  descriptionKey: string;
  fallbackDescription: string;
}

interface SystemGroup {
  key: string;
  titleKey: string;
  fallbackTitle: string;
  descriptionKey: string;
  fallbackDescription: string;
  options: ModeOption[];
}

const PRESETS: PresetOption[] = GAWORLD_PRESET_KEYS.map((key) => ({
  key,
  modes: getGAWorldPresetModes(key),
}));

const SYSTEM_GROUPS: SystemGroup[] = [
  {
    key: 'information_mode',
    titleKey: 'experimentBuilder.gaworld.groups.information.title',
    fallbackTitle: 'Information',
    descriptionKey: 'experimentBuilder.gaworld.groups.information.description',
    fallbackDescription: 'How much outside information moves through the city.',
    options: [
      {
        key: 'off',
        titleKey: 'experimentBuilder.gaworld.modes.information.off.title',
        fallbackTitle: 'Off',
        descriptionKey: 'experimentBuilder.gaworld.modes.information.off.description',
        fallbackDescription: 'People do not react to outside information sources.',
      },
      {
        key: 'city_news',
        titleKey: 'experimentBuilder.gaworld.modes.information.city_news.title',
        fallbackTitle: 'City news only',
        descriptionKey: 'experimentBuilder.gaworld.modes.information.city_news.description',
        fallbackDescription: 'People receive shared news without active seeking.',
      },
      {
        key: 'active_flow',
        titleKey: 'experimentBuilder.gaworld.modes.information.active_flow.title',
        fallbackTitle: 'Active information flow',
        descriptionKey: 'experimentBuilder.gaworld.modes.information.active_flow.description',
        fallbackDescription: 'People receive shared news and actively seek more.',
      },
    ],
  },
  {
    key: 'daily_life_mode',
    titleKey: 'experimentBuilder.gaworld.groups.daily_life.title',
    fallbackTitle: 'Daily Life',
    descriptionKey: 'experimentBuilder.gaworld.groups.daily_life.description',
    fallbackDescription: 'How fixed or flexible daily routines are.',
    options: [
      {
        key: 'stable_routines',
        titleKey: 'experimentBuilder.gaworld.modes.daily_life.stable_routines.title',
        fallbackTitle: 'Stable routines',
        descriptionKey: 'experimentBuilder.gaworld.modes.daily_life.stable_routines.description',
        fallbackDescription: 'Daily plans mostly repeat with little variation.',
      },
      {
        key: 'some_variation',
        titleKey: 'experimentBuilder.gaworld.modes.daily_life.some_variation.title',
        fallbackTitle: 'Some variation',
        descriptionKey: 'experimentBuilder.gaworld.modes.daily_life.some_variation.description',
        fallbackDescription: 'Daily life changes sometimes without becoming chaotic.',
      },
      {
        key: 'flexible_daily_life',
        titleKey: 'experimentBuilder.gaworld.modes.daily_life.flexible_daily_life.title',
        fallbackTitle: 'Flexible daily life',
        descriptionKey: 'experimentBuilder.gaworld.modes.daily_life.flexible_daily_life.description',
        fallbackDescription: 'Plans shift often and leave room for more improvisation.',
      },
    ],
  },
  {
    key: 'people_mode',
    titleKey: 'experimentBuilder.gaworld.groups.people.title',
    fallbackTitle: 'People',
    descriptionKey: 'experimentBuilder.gaworld.groups.people.description',
    fallbackDescription: 'How adaptive and human-like people behave.',
    options: [
      {
        key: 'simple_behavior',
        titleKey: 'experimentBuilder.gaworld.modes.people.simple_behavior.title',
        fallbackTitle: 'Simple behavior',
        descriptionKey: 'experimentBuilder.gaworld.modes.people.simple_behavior.description',
        fallbackDescription: 'People behave in a more basic and predictable way.',
      },
      {
        key: 'adaptive_behavior',
        titleKey: 'experimentBuilder.gaworld.modes.people.adaptive_behavior.title',
        fallbackTitle: 'Adaptive behavior',
        descriptionKey: 'experimentBuilder.gaworld.modes.people.adaptive_behavior.description',
        fallbackDescription: 'People respond to their situation in a moderate way.',
      },
      {
        key: 'rich_human_behavior',
        titleKey: 'experimentBuilder.gaworld.modes.people.rich_human_behavior.title',
        fallbackTitle: 'Rich human behavior',
        descriptionKey: 'experimentBuilder.gaworld.modes.people.rich_human_behavior.description',
        fallbackDescription: 'People show richer adaptation and human detail.',
      },
    ],
  },
  {
    key: 'memory_mode',
    titleKey: 'experimentBuilder.gaworld.groups.memory.title',
    fallbackTitle: 'Memory',
    descriptionKey: 'experimentBuilder.gaworld.groups.memory.description',
    fallbackDescription: 'How much people carry forward from previous days.',
    options: [
      {
        key: 'in_the_moment',
        titleKey: 'experimentBuilder.gaworld.modes.memory.in_the_moment.title',
        fallbackTitle: 'In-the-moment',
        descriptionKey: 'experimentBuilder.gaworld.modes.memory.in_the_moment.description',
        fallbackDescription: 'People mostly act on the current day.',
      },
      {
        key: 'some_continuity',
        titleKey: 'experimentBuilder.gaworld.modes.memory.some_continuity.title',
        fallbackTitle: 'Some continuity',
        descriptionKey: 'experimentBuilder.gaworld.modes.memory.some_continuity.description',
        fallbackDescription: 'People carry some recent context forward.',
      },
      {
        key: 'rich_memory',
        titleKey: 'experimentBuilder.gaworld.modes.memory.rich_memory.title',
        fallbackTitle: 'Rich memory',
        descriptionKey: 'experimentBuilder.gaworld.modes.memory.rich_memory.description',
        fallbackDescription: 'People build stronger continuity across days.',
      },
    ],
  },
];

function getStringValue(params: Record<string, unknown>, key: string, fallback: string): string {
  const rawValue = params[key];
  return typeof rawValue === 'string' && rawValue.trim() ? rawValue : fallback;
}

export default function GAWorldScenarioPanel({
  scenarioParams,
  setScenarioParams,
}: GAWorldScenarioPanelProps) {
  const { t } = useTranslation();
  const [showAdvanced, setShowAdvanced] = React.useState(false);
  const activePreset = getStringValue(scenarioParams, 'execution_profile', 'fast');

  const applyPreset = (preset: PresetOption) => {
    setScenarioParams({
      ...scenarioParams,
      execution_profile: preset.key,
      ...preset.modes,
    });
  };

  const updateMode = (key: string, value: string) => {
    setScenarioParams({
      ...scenarioParams,
      [key]: value,
    });
  };

  const updateSeed = (rawValue: string) => {
    const parsed = Number.parseInt(rawValue, 10);
    setScenarioParams({
      ...scenarioParams,
      seed: Number.isNaN(parsed) ? 0 : parsed,
    });
  };

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-medium" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.gaworld.startingPointTitle', { defaultValue: 'Starting point' })}
          </h3>
          <p className="text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
            {t('experimentBuilder.gaworld.startingPointHint', {
              defaultValue: 'Choose a starter mode, then fine-tune the city systems below.',
            })}
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {PRESETS.map((preset) => {
            const isActive = activePreset === preset.key;
            return (
              <button
                key={preset.key}
                type="button"
                onClick={() => applyPreset(preset)}
                className="rounded-xl border p-4 text-left transition-colors"
                style={{
                  borderColor: isActive ? 'var(--ss-brand-primary)' : 'var(--ss-border)',
                  background: isActive ? 'var(--ss-brand-soft)' : 'var(--ss-page-surface)',
                }}
              >
                <div className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                  {t(`experimentBuilder.gaworld.presets.${preset.key}.title`, {
                    defaultValue: preset.key === 'full_fidelity' ? 'Full' : preset.key[0].toUpperCase() + preset.key.slice(1),
                  })}
                </div>
                <p className="mt-2 text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
                  {t(`experimentBuilder.gaworld.presets.${preset.key}.description`, {
                    defaultValue: '',
                  })}
                </p>
              </button>
            );
          })}
        </div>
      </section>

      <section className="space-y-4">
        <div>
          <h3 className="text-sm font-medium" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.gaworld.citySystemsTitle', { defaultValue: 'City systems' })}
          </h3>
        </div>
        {SYSTEM_GROUPS.map((group) => {
          const selectedValue = getStringValue(
            scenarioParams,
            group.key,
            group.options[1]?.key || group.options[0].key,
          );
          return (
            <div
              key={group.key}
              className="rounded-xl border p-4"
              style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)' }}
            >
              <h4 className="text-sm font-semibold" style={{ color: 'var(--ss-heading)' }}>
                {t(group.titleKey, { defaultValue: group.fallbackTitle })}
              </h4>
              <p className="mt-1 text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
                {t(group.descriptionKey, { defaultValue: group.fallbackDescription })}
              </p>
              <div className="mt-3 grid gap-3 md:grid-cols-3">
                {group.options.map((option) => {
                  const isSelected = selectedValue === option.key;
                  return (
                    <button
                      key={option.key}
                      type="button"
                      onClick={() => updateMode(group.key, option.key)}
                      className="rounded-xl border p-3 text-left transition-colors"
                      style={{
                        borderColor: isSelected ? 'var(--ss-brand-primary)' : 'var(--ss-border)',
                        background: isSelected ? 'var(--ss-brand-soft)' : 'var(--ss-page-surface-muted)',
                      }}
                    >
                      <div className="text-sm font-medium" style={{ color: 'var(--ss-heading)' }}>
                        {t(option.titleKey, { defaultValue: option.fallbackTitle })}
                      </div>
                      <p className="mt-2 text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
                        {t(option.descriptionKey, { defaultValue: option.fallbackDescription })}
                      </p>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </section>

      <section className="space-y-3">
        <button
          type="button"
          onClick={() => setShowAdvanced((current) => !current)}
          className="rounded-lg border px-4 py-2 text-sm font-medium"
          style={{ borderColor: 'var(--ss-border)', color: 'var(--ss-heading)' }}
        >
          {t('experimentBuilder.gaworld.advancedTitle', { defaultValue: 'Advanced' })}
        </button>
        {showAdvanced && (
          <div className="rounded-xl border p-4" style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)' }}>
            <label className="block text-sm font-medium" style={{ color: 'var(--ss-heading)' }}>
              {t('experimentBuilder.gaworld.seedLabel', { defaultValue: 'Reproducibility seed' })}
            </label>
            <p className="mt-1 text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
              {t('experimentBuilder.gaworld.seedDescription', {
                defaultValue: 'Use the same seed to repeat the same setup.',
              })}
            </p>
            <input
              type="number"
              value={Number(scenarioParams.seed ?? 42)}
              onChange={(event) => updateSeed(event.target.value)}
              className="mt-3 w-full rounded-lg border px-3 py-2"
              style={{ borderColor: 'var(--ss-border-strong)' }}
            />
          </div>
        )}
      </section>
    </div>
  );
}
