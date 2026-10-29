/**
 * Step1TemplateSelection component for SimulationWizard.
 *
 * Template selection UI with system presets, custom templates, and template builder.
 *
 * Props:
 *   - activeTab: Current tab ('system' | 'custom')
 *   - useCustomTemplate: Whether custom template builder is active
 *   - selectedTemplateId: ID of selected template
 *   - savedTemplates: List of saved templates
 *   - onTabChange: Callback when tab is changed
 *   - onTemplateSelect: Callback when template is selected
 *   - onUseCustomTemplate: Callback to enable custom template builder
 *   - onDeleteTemplate: Callback when template is deleted
 *   - genericTemplate: Generic template configuration
 *   - systemPresetsText: Translation for system presets tab
 *   - myTemplatesText: Translation for my templates tab
 *   - customTemplateBuilderText: Translation for custom template builder
 *   - noSystemTemplatesText: Translation for empty system templates
 *   - noCustomTemplatesText: Translation for empty custom templates
 *   - agentsText: Translation for agents count
 */

import React from 'react';
import { Trash2, LayoutTemplate, Settings, Users } from 'lucide-react';
import { Template } from '../../types';

interface Step1TemplateSelectionProps {
  activeTab: 'system' | 'custom';
  useCustomTemplate: boolean;
  selectedTemplateId: string;
  savedTemplates: Template[];
  genericTemplate: any;
  onTabChange: (tab: 'system' | 'custom') => void;
  onTemplateSelect: (id: string) => void;
  onUseCustomTemplate: () => void;
  onDeleteTemplate: (e: React.MouseEvent, id: string) => void;
  t: (key: string) => string;
}

export const Step1TemplateSelection: React.FC<Step1TemplateSelectionProps> = ({
  activeTab,
  useCustomTemplate,
  selectedTemplateId,
  savedTemplates,
  genericTemplate,
  onTabChange,
  onTemplateSelect,
  onUseCustomTemplate,
  onDeleteTemplate,
  t,
}) => {
  const selectedTemplate =
    savedTemplates.find((tpl) => tpl.id === selectedTemplateId) ||
    savedTemplates[0];

  return (
    <div>
      <label className="block text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
        <LayoutTemplate size={16} />
        {t('wizard.step1.selectSceneTemplate')}
      </label>

      <div className="flex gap-4 border-b border-slate-200 mb-4">
        <button
          onClick={() => {
            onTabChange('system');
          }}
          className={`pb-2 text-sm font-medium transition-colors ${
            activeTab === 'system' && !useCustomTemplate
              ? 'text-brand-600 border-b-2 border-brand-600'
              : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          {t('wizard.step1.systemPresets')}
        </button>
        <button
          onClick={() => {
            onTabChange('custom');
          }}
          className={`pb-2 text-sm font-medium transition-colors ${
            activeTab === 'custom' && !useCustomTemplate
              ? 'text-brand-600 border-b-2 border-brand-600'
              : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          {t('wizard.step1.myTemplates')}
        </button>
        <button
          onClick={onUseCustomTemplate}
          className={`pb-2 text-sm font-medium transition-colors flex items-center gap-1 ${
            useCustomTemplate
              ? 'text-purple-600 border-b-2 border-purple-600'
              : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          <Settings size={14} />
          {t('wizard.step1.customTemplateBuilder')}
        </button>
      </div>

      {/* System/Custom Templates */}
      {!useCustomTemplate && (
        <div className="grid grid-cols-3 gap-4">
          {savedTemplates.filter((tpl) => tpl.category === activeTab)
            .length === 0 ? (
            <div className="col-span-3 py-8 text-center text-slate-400 bg-slate-50 rounded-lg border border-dashed">
              {activeTab === 'custom'
                ? t('wizard.step1.noCustomTemplates')
                : t('wizard.step1.noSystemTemplates')}
            </div>
          ) : (
            savedTemplates
              .filter((tpl) => tpl.category === activeTab)
              .map((tpl) => (
                <div
                  key={tpl.id}
                  onClick={() => onTemplateSelect(tpl.id)}
                  className={`p-4 border rounded-lg text-left transition-all cursor-pointer relative group ${
                    selectedTemplateId === tpl.id && !useCustomTemplate
                      ? 'border-brand-500 ring-2 ring-brand-100 bg-brand-50'
                      : 'hover:border-slate-300 hover:bg-slate-50'
                  }`}
                >
                  <div className="font-bold text-slate-800">
                    {tpl.category === 'system'
                      ? t(`systemTemplates.${tpl.id}.name`)
                      : tpl.name}
                  </div>
                  <div className="text-xs text-slate-500 mt-1 line-clamp-2">
                    {tpl.category === 'system'
                      ? t(`systemTemplates.${tpl.id}.description`)
                      : tpl.description}
                  </div>

                  {tpl.category === 'custom' && (
                    <button
                      onClick={(e) => onDeleteTemplate(e, tpl.id)}
                      className="absolute top-2 right-2 p-1 text-slate-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}

                  {tpl.category === 'custom' && (
                    <div className="mt-2 flex items-center gap-1 text-[10px] text-brand-600 bg-brand-100 px-1.5 py-0.5 rounded w-fit">
                      <Users size={10} /> {tpl.agents?.length || 0} {t('wizard.agents')}
                    </div>
                  )}
                </div>
              ))
          )}
        </div>
      )}

      {/* Custom Template Builder */}
      {useCustomTemplate && (
        <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Settings className="text-purple-600" size={18} />
              <span className="text-sm font-bold text-purple-900">
                {t('wizard.step1.customTemplateBuilderTitle')}
              </span>
            </div>
          </div>
          <p className="text-xs text-purple-700 mb-3">
            {t('wizard.step1.customTemplateBuilderDesc')}
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
            <div className="bg-white rounded p-2 text-center">
              <div className="font-bold text-purple-700">{genericTemplate.coreMechanics.filter((m: any) => m.enabled).length}</div>
              <div className="text-slate-500">{t('wizard.step1.enabledMechanisms')}</div>
            </div>
            <div className="bg-white rounded p-2 text-center">
              <div className="font-bold text-purple-700">{genericTemplate.availableActions.length}</div>
              <div className="text-slate-500">{t('wizard.step1.availableActions')}</div>
            </div>
            <div className="bg-white rounded p-2 text-center">
              <div className="font-bold text-purple-700">{(genericTemplate.environment.rules?.length || 0)}</div>
              <div className="text-slate-500">{t('wizard.step1.environmentRules')}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
