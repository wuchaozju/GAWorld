/**
 * Resource configuration component for Public Goods Game.
 *
 * Simplified UI with free text resource name and NumberField steppers.
 * Uses neutral language (allocate/deduct) matching backend.
 *
 * Exports: ResourceConfig (default)
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import NumberField from './parameter_widgets/NumberField';

interface ResourceConfigProps {
  values: {
    resource_name: string;
    tokens_per_round: number;
    multiplier: number;
    deduction_budget_per_phase: number;
    deduction_cost_ratio: number;
    deduction_anonymous: boolean;
    show_average_contribution: boolean;
  };
  onChange: (key: string, value: string | number | boolean) => void;
}

export const ResourceConfig: React.FC<ResourceConfigProps> = ({
  values,
  onChange,
}) => {
  const { t } = useTranslation();

  return (
    <div className="space-y-6">
      {/* Resource Settings */}
      <div className="space-y-4">
        <h3 className="text-sm font-medium" style={{ color: 'var(--ss-heading)' }}>
          {t('experimentBuilder.resourceConfig.title')}
        </h3>

        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.resourceConfig.resourceNameLabel')}
          </label>
          <input
            type="text"
            value={values.resource_name}
            onChange={(e) => onChange('resource_name', e.target.value)}
            placeholder="tokens"
            className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2"
            style={{ borderColor: 'var(--ss-border-strong)' }}
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.resourceConfig.amountPerRoundLabel')}
          </label>
          <NumberField
            value={values.tokens_per_round}
            onChange={(v) => onChange('tokens_per_round', v)}
            min={1}
            max={1000}
            step={1}
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.resourceConfig.multiplierLabel')}
          </label>
          <NumberField
            value={values.multiplier}
            onChange={(v) => onChange('multiplier', v)}
            min={0.01}
            max={100}
            step={0.01}
          />
        </div>
      </div>

      {/* Deduction Settings */}
      <div className="space-y-4 border-t pt-4" style={{ borderColor: 'var(--ss-border)' }}>
        <h3 className="text-sm font-medium" style={{ color: 'var(--ss-heading)' }}>
          {t('experimentBuilder.deductionSettings.title')}
        </h3>

        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.deductionSettings.budgetLabel')}
          </label>
          <NumberField
            value={values.deduction_budget_per_phase}
            onChange={(v) => onChange('deduction_budget_per_phase', v)}
            min={0}
            max={100}
            step={1}
          />
          <p className="text-xs mt-1" style={{ color: 'var(--ss-text-muted)' }}>
            {t('experimentBuilder.deductionSettings.budgetHint')}
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.deductionSettings.costRatioLabel')}
          </label>
          <NumberField
            value={values.deduction_cost_ratio}
            onChange={(v) => onChange('deduction_cost_ratio', v)}
            min={1.0}
            max={10.0}
            step={0.1}
          />
          <p className="text-xs mt-1" style={{ color: 'var(--ss-text-muted)' }}>
            {t('experimentBuilder.deductionSettings.costRatioHint')}
          </p>
        </div>

        <div className="flex items-center">
          <input
            type="checkbox"
            id="deduction_anonymous"
            checked={values.deduction_anonymous}
            onChange={(e) => onChange('deduction_anonymous', e.target.checked)}
            className="h-4 w-4 rounded" style={{ accentColor: 'var(--ss-brand-primary)', borderColor: 'var(--ss-border-strong)' }}
          />
          <label htmlFor="deduction_anonymous" className="ml-2 block text-sm" style={{ color: 'var(--ss-heading)' }}>
            {t('experimentBuilder.deductionSettings.anonymousLabel')}
          </label>
        </div>
      </div>

      {/* Average Contribution Display */}
      <div className="space-y-4 border-t pt-4" style={{ borderColor: 'var(--ss-border)' }}>
        <h3 className="text-sm font-medium" style={{ color: 'var(--ss-heading)' }}>
          {t('experimentBuilder.resourceConfig.displaySettingsTitle')}
        </h3>

        <div className="flex items-start">
          <input
            type="checkbox"
            id="show_average_contribution"
            checked={values.show_average_contribution}
            onChange={(e) => onChange('show_average_contribution', e.target.checked)}
            className="h-4 w-4 rounded mt-0.5" style={{ accentColor: 'var(--ss-brand-primary)' }}
          />
          <div className="ml-2">
            <label htmlFor="show_average_contribution" className="block text-sm" style={{ color: 'var(--ss-text)' }}>
              {t('experimentBuilder.resourceConfig.showAverageLabel')}
            </label>
            <p className="text-xs mt-1" style={{ color: 'var(--ss-text-subtle)' }}>
              {t('experimentBuilder.resourceConfig.showAverageHint')}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ResourceConfig;
