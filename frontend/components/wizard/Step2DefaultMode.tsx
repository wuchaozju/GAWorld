/**
 * Step2DefaultMode component for SimulationWizard.
 *
 * Display for when using template's default agents.
 *
 * Props:
 *   - template: Selected template object
 *   - systemPresetsText: Text prefix for system templates
 *   - customAgentsText: Text for custom agents count
 *   - systemAgentsText: Text for system agents count
 */

import React from 'react';
import { Users } from 'lucide-react';
import { Template } from '../../types';

interface Step2DefaultModeProps {
  template: Template;
  t: (key: string, params?: any) => string;
}

export const Step2DefaultMode: React.FC<Step2DefaultModeProps> = ({ template, t }) => {
  const getAgentCount = () => {
    if (template.category === 'custom') {
      return template.agents?.length || 0;
    }
    // System template agent counts
    if (template.sceneType === 'council') return 5;
    if (template.sceneType === 'werewolf') return 9;
    return 2;
  };

  return (
    <div className="text-center py-10 bg-slate-50 rounded-lg border border-dashed border-slate-300">
      <div className="w-16 h-16 bg-blue-100 text-blue-500 rounded-full flex items-center justify-center mx-auto mb-4">
        <Users size={32} />
      </div>
      <h3 className="text-lg font-bold text-slate-700">
        {t('wizard.step2.usingPresetAgents')}{' '}
        <span className="text-brand-600">
          {template.category === 'system'
            ? t(`systemTemplates.${template.id}.name`)
            : template.name}
        </span>{' '}
        {template.category === 'custom'
          ? t('wizard.step2.customTemplateAgents', { count: getAgentCount() })
          : t('wizard.step2.systemTemplateAgents', { count: getAgentCount() })}
      </h3>
      <p className="text-slate-500 mt-2 text-sm max-w-md mx-auto">
        {template.category === 'custom'
          ? t('wizard.step2.customTemplateAgents', { count: getAgentCount() })
          : t('wizard.step2.systemTemplateAgents', { count: getAgentCount() })}
      </p>
    </div>
  );
};
