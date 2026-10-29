/**
 * Step3Confirmation component for SimulationWizard.
 *
 * Confirmation summary showing simulation configuration before starting.
 *
 * Props:
 *   - useCustomTemplate: Whether using custom template
 *   - genericTemplate: Generic template configuration
 *   - selectedTemplate: Selected template object
 *   - customAgents: Custom imported/generated agents
 *   - timeUnit: Time unit for simulation
 *   - timeStep: Time step per turn
 *   - t: Translation function
 */

import React from 'react';
import { Check } from 'lucide-react';
import { Template, TimeUnit } from '../../types';

interface Step3ConfirmationProps {
  useCustomTemplate: boolean;
  genericTemplate: any;
  selectedTemplate: Template;
  customAgents: any[];
  timeUnit: TimeUnit;
  timeStep: number;
  t: (key: string) => string;
}

export const Step3Confirmation: React.FC<Step3ConfirmationProps> = ({
  useCustomTemplate,
  genericTemplate,
  selectedTemplate,
  customAgents,
  timeUnit,
  timeStep,
  t,
}) => {
  const getTimeUnitLabel = () => {
    const units: Record<TimeUnit, string> = {
      minute: t('wizard.timeUnits.minute'),
      hour: t('wizard.timeUnits.hour'),
      day: t('wizard.timeUnits.day'),
      week: t('wizard.timeUnits.week'),
      month: t('wizard.timeUnits.month'),
      year: t('wizard.timeUnits.year'),
    };
    return units[timeUnit] || timeUnit;
  };

  return (
    <div className="space-y-4 text-center py-8">
      <div className="w-16 h-16 bg-green-100 text-green-600 rounded-full flex items-center justify-center mx-auto mb-4">
        <Check size={32} />
      </div>
      <h3 className="text-xl font-bold text-slate-800">
        {t('wizard.step3.ready')}
      </h3>
      <div className="bg-slate-50 rounded-lg p-6 max-w-md mx-auto text-left space-y-3 border">
        {useCustomTemplate ? (
          <>
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">{t('wizard.step3.templateType')}:</span>
              <span className="font-bold text-purple-700">
                {t('wizard.step3.customTemplate')}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">{t('wizard.step3.templateName')}:</span>
              <span className="font-bold text-slate-800">
                {genericTemplate.name || t('wizard.step3.unnamed')}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">{t('wizard.step3.coreMechanisms')}:</span>
              <span className="font-bold text-slate-800">
                {genericTemplate.coreMechanics.filter((m: any) => m.enabled)
                  .map((m: any) => m.type)
                  .join(', ') || t('wizard.step3.none')}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">{t('wizard.step3.availableActionsCount')}:</span>
              <span className="font-bold text-slate-800">
                {genericTemplate.availableActions.length} {t('wizard.step1.availableActions')}
              </span>
            </div>
          </>
        ) : (
          <>
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">{t('wizard.step3.template')}:</span>
              <span className="font-bold text-slate-800">
                {selectedTemplate.category === 'system'
                  ? t(`systemTemplates.${selectedTemplate.id}.name`)
                  : selectedTemplate.name}
              </span>
            </div>
            {(customAgents.length > 0) && (
              <div className="flex justify-between text-sm">
                <span className="text-slate-500">{t('wizard.step3.customAgents')}:</span>
                <span className="font-bold text-brand-600">
                  {customAgents.length} {t('wizard.step3.people')}
                </span>
              </div>
            )}
          </>
        )}
        <div className="flex justify-between text-sm">
          <span className="text-slate-500">{t('wizard.step3.timeFlow')}:</span>
          <span className="font-bold text-slate-800">
            {t('wizard.step3.perTurn')} {timeStep}{' '}
            {getTimeUnitLabel()}
          </span>
        </div>
      </div>
    </div>
  );
};
