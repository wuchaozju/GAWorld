// frontend/components/TemplateBuilder.tsx
import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Plus,
  Trash2,
  Settings,
  Zap,
  Globe
} from 'lucide-react';
import {
  CoreMechanicConfig,
  CoreMechanicType,
  GenericTemplateConfig,
  TimeConfig,
  TimeUnit
} from '../types';

interface TemplateBuilderProps {
  template: GenericTemplateConfig;
  onChange: (template: GenericTemplateConfig) => void;
  timeConfig?: TimeConfig;
  onTimeConfigChange?: (config: TimeConfig) => void;
}

const TIME_UNITS: { value: TimeUnit; label: string }[] = [
  { value: 'minute', label: '' },
  { value: 'hour', label: '' },
  { value: 'day', label: '' },
  { value: 'week', label: '' },
  { value: 'month', label: '' },
  { value: 'year', label: '' }
];

const CORE_MECHANIC_DEFINITIONS: Record<CoreMechanicType, { name: string; description: string; configFields?: { key: string; label: string; type: 'text' | 'number' | 'boolean'; default: any }[] }> = {
  grid: {
    name: '',
    description: '',
    configFields: [
      { key: 'width', label: '', type: 'number', default: 10 },
      { key: 'height', label: '', type: 'number', default: 10 },
      { key: 'wrapAround', label: '', type: 'boolean', default: false }
    ]
  },
  discussion: {
    name: '',
    description: '',
    configFields: [
      { key: 'maxTurns', label: '', type: 'number', default: 3 },
      { key: 'allowInterruption', label: '', type: 'boolean', default: false }
    ]
  },
  voting: {
    name: '',
    description: '',
    configFields: [
      { key: 'quorum', label: '', type: 'number', default: 50 },
      { key: 'majority', label: '', type: 'number', default: 51 }
    ]
  },
  resources: {
    name: '',
    description: '',
    configFields: [
      { key: 'initialAmount', label: '', type: 'number', default: 100 },
      { key: 'renewable', label: '', type: 'boolean', default: true }
    ]
  },
  hierarchy: {
    name: '',
    description: '',
    configFields: [
      { key: 'levels', label: '', type: 'number', default: 3 },
      { key: 'enforceChain', label: '', type: 'boolean', default: true }
    ]
  },
  time: {
    name: '',
    description: '',
    configFields: []
  }
};

// Available system actions from backend ACTION_SPACE_MAP
const SYSTEM_ACTIONS = [
  // Communication
  { id: 'send_message', category: 'communication' },
  { id: 'talk_to', category: 'communication' },
  { id: 'speak', category: 'communication' },
  { id: 'yield', category: 'communication' },
  // Movement
  { id: 'move', category: 'movement' },
  { id: 'move_to_location', category: 'movement' },  // legacy alias
  // Observation
  { id: 'look_around', category: 'observation' },
  // Rest / idle (record-only in active scenarios)
  { id: 'rest', category: 'observation' },
  // Tools
  { id: 'web_search', category: 'tools' },
  { id: 'view_page', category: 'tools' },
  { id: 'query_knowledge', category: 'tools' },
  { id: 'list_knowledge', category: 'tools' },
  // Council
  { id: 'start_voting', category: 'council' },
  { id: 'vote', category: 'council' },
  { id: 'finish_meeting', category: 'council' },
  { id: 'request_brief', category: 'council' },
  { id: 'voting_status', category: 'council' },
  { id: 'schedule_order', category: 'council' },
  // Werewolf
  { id: 'vote_lynch', category: 'werewolf' },
  { id: 'night_kill', category: 'werewolf' },
  { id: 'inspect', category: 'werewolf' },
  { id: 'witch_save', category: 'werewolf' },
  { id: 'witch_poison', category: 'werewolf' },
  { id: 'open_voting', category: 'werewolf' },
  { id: 'close_voting', category: 'werewolf' },
  // Landlord
  { id: 'call_landlord', category: 'landlord' },
  { id: 'rob_landlord', category: 'landlord' },
  { id: 'pass', category: 'landlord' },
  { id: 'play_cards', category: 'landlord' },
  { id: 'double', category: 'landlord' },
  { id: 'no_double', category: 'landlord' },
];

const ACTION_CATEGORIES = ['communication', 'movement', 'observation', 'tools', 'council', 'werewolf', 'landlord'] as const;

// Action to required mechanic mapping
// When these actions are selected, the corresponding mechanic will be auto-enabled
const ACTION_MECHANIC_REQUIREMENTS: Record<string, CoreMechanicType[]> = {
  // Movement & Observation actions require Grid
  move: ['grid'],
  look_around: ['grid'],
  rest: ['grid'],  // Rest is record-only, needs grid for context
  // Voting actions require Voting
  start_voting: ['voting'],
  vote: ['voting'],
  voting_status: ['voting'],
  finish_meeting: ['voting'],
  request_brief: ['voting'],
  // Council discussion requires Discussion
  schedule_order: ['discussion'],
  // Werewolf actions have special requirements
  vote_lynch: ['voting'],
  night_kill: [],
  inspect: [],
  witch_save: [],
  witch_poison: [],
  open_voting: ['voting'],
  close_voting: ['voting'],
  // Landlord actions
  call_landlord: [],
  rob_landlord: [],
  pass: [],
  play_cards: [],
  double: [],
  no_double: [],
};

const generateId = () => `${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;

const createEmptyCoreMechanic = (type: CoreMechanicType): CoreMechanicConfig => {
  const def = CORE_MECHANIC_DEFINITIONS[type];
  const config: Record<string, any> = {};
  def.configFields?.forEach(field => {
    config[field.key] = field.default;
  });
  return { type, enabled: false, config };
};

export const TemplateBuilder: React.FC<TemplateBuilderProps> = ({
  template,
  onChange,
  timeConfig,
  onTimeConfigChange
}) => {
  const { t } = useTranslation();
  const [expandedMechanic, setExpandedMechanic] = useState<CoreMechanicType | null>(null);

  const updateTemplate = (updates: Partial<GenericTemplateConfig>) => {
    onChange({ ...template, ...updates });
  };

  const updateBasicInfo = (field: 'name' | 'description', value: string) => {
    updateTemplate({ [field]: value });
  };

  const toggleCoreMechanic = (type: CoreMechanicType) => {
    const updated = template.coreMechanics.map(m =>
      m.type === type ? { ...m, enabled: !m.enabled } : m
    );
    updateTemplate({ coreMechanics: updated });
  };

  const updateCoreMechanicConfig = (type: CoreMechanicType, key: string, value: any) => {
    const updated = template.coreMechanics.map(m =>
      m.type === type ? { ...m, config: { ...m.config, [key]: value } } : m
    );
    updateTemplate({ coreMechanics: updated });
  };

  const toggleAction = (actionId: string, checked: boolean) => {
    // Update actions
    const currentActions = new Set(template.availableActions || []);
    if (checked) {
      currentActions.add(actionId);
    } else {
      currentActions.delete(actionId);
    }
    const newAvailableActions = Array.from(currentActions);

    // Auto-enable required mechanics when actions are selected
    const requiredMechanics = ACTION_MECHANIC_REQUIREMENTS[actionId];
    let newCoreMechanics = template.coreMechanics;
    if (requiredMechanics && requiredMechanics.length > 0 && checked) {
      newCoreMechanics = template.coreMechanics.map(m =>
        requiredMechanics.includes(m.type)
          ? { ...m, enabled: true }
          : m
      );
    }

    // Single atomic update
    updateTemplate({
      availableActions: newAvailableActions,
      coreMechanics: newCoreMechanics
    });
  };

  const isActionSelected = (actionId: string) => {
    return (template.availableActions || []).includes(actionId);
  };

  const updateEnvironment = (field: 'description' | 'rules', value: any) => {
    updateTemplate({
      environment: { ...template.environment, [field]: value }
    });
  };

  const addEnvironmentRule = () => {
    const rules = template.environment.rules || [];
    updateTemplate({
      environment: { ...template.environment, rules: [...rules, ''] }
    });
  };

  const updateEnvironmentRule = (index: number, value: string) => {
    const rules = template.environment.rules || [];
    updateTemplate({
      environment: {
        ...template.environment,
        rules: rules.map((r, i) => i === index ? value : r)
      }
    });
  };

  const removeEnvironmentRule = (index: number) => {
    const rules = template.environment.rules || [];
    updateTemplate({
      environment: {
        ...template.environment,
        rules: rules.filter((_, i) => i !== index)
      }
    });
  };

  const updateTimeConfig = (field: keyof TimeConfig, value: any) => {
    if (onTimeConfigChange) {
      onTimeConfigChange({ ...timeConfig!, [field]: value });
    }
  };

  // Group actions by category
  const actionsByCategory = SYSTEM_ACTIONS.reduce((acc, action) => {
    if (!acc[action.category]) {
      acc[action.category] = [];
    }
    acc[action.category].push(action);
    return acc;
  }, {} as Record<string, typeof SYSTEM_ACTIONS>);

  return (
    <div className="space-y-6">
      {/* Basic Information */}
      <div className="border border-slate-200 rounded-lg p-4">
        <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center gap-2">
          <Settings size={16} />
          {t('templateBuilder.basicInfo', { defaultValue: 'Basic Information' })}
        </h3>
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              {t('templateBuilder.templateName', { defaultValue: 'Template Name' })}
            </label>
            <input
              type="text"
              value={template.name}
              onChange={(e) => updateBasicInfo('name', e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-500 outline-none"
              placeholder={t('templateBuilder.placeholders.name', { defaultValue: 'e.g., Town Hall Meeting' })}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              {t('templateBuilder.description', { defaultValue: 'Description' })}
            </label>
            <textarea
              value={template.description}
              onChange={(e) => updateBasicInfo('description', e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-500 outline-none resize-none"
              rows={2}
              placeholder={t('templateBuilder.placeholders.description', { defaultValue: 'Describe what this template simulates...' })}
            />
          </div>
        </div>
      </div>

      {/* Core Mechanics */}
      <div className="border border-slate-200 rounded-lg p-4">
        <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center gap-2">
          <Zap size={16} />
          {t('templateBuilder.coreMechanics', { defaultValue: 'Core Mechanics' })}
        </h3>
        <p className="text-xs text-slate-500 mb-4">
          {t('templateBuilder.coreMechanicsHint', { defaultValue: 'Select the core mechanics to enable in this template' })}
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {Object.entries(CORE_MECHANIC_DEFINITIONS).map(([type, def]) => {
            const mechanic = template.coreMechanics.find(m => m.type === type);
            const isEnabled = mechanic?.enabled || false;

            return (
              <div key={type} className="border border-slate-200 rounded-lg p-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={isEnabled}
                      onChange={() => toggleCoreMechanic(type as CoreMechanicType)}
                      className="w-4 h-4 text-brand-600 rounded focus:ring-brand-500"
                    />
                    <span className="font-medium text-sm text-slate-700">{t(`templateBuilder.mechanics.${type}`)}</span>
                  </div>
                  <button
                    onClick={() => setExpandedMechanic(expandedMechanic === type ? null : type as CoreMechanicType)}
                    className="text-xs text-slate-500 hover:text-slate-700"
                  >
                    {expandedMechanic === type ? '▲' : '▼'}
                  </button>
                </div>
                <p className="text-xs text-slate-500 mb-2">{t(`templateBuilder.mechanics.${type}Description`)}</p>

                {isEnabled && expandedMechanic === type && def.configFields && (
                  <div className="mt-3 pt-3 border-t border-slate-100 space-y-2">
                    {def.configFields.map((field, index) => {
                      const labelKey = `templateBuilder.configFields.${{
                        width: 'gridWidth',
                        height: 'gridHeight',
                        wrapAround: 'wrapAround',
                        maxTurns: 'maxTurns',
                        allowInterruption: 'allowInterruption',
                        quorum: 'quorum',
                        majority: 'majority',
                        initialAmount: 'initialAmount',
                        renewable: 'renewable',
                        levels: 'levels',
                        enforceChain: 'enforceChain'
                      }[field.key] || field.key}`;
                      return (
                        <div key={field.key}>
                          <label className="block text-xs text-slate-600 mb-1">{t(labelKey)}</label>
                          {field.type === 'boolean' ? (
                            <select
                              value={mechanic?.config[field.key]?.toString() || field.default.toString()}
                              onChange={(e) => updateCoreMechanicConfig(type as CoreMechanicType, field.key, e.target.value === 'true')}
                              className="w-full px-2 py-1 border border-slate-200 rounded text-sm"
                            >
                              <option value="true">{t('common.yes', { defaultValue: 'Yes' })}</option>
                              <option value="false">{t('common.no', { defaultValue: 'No' })}</option>
                            </select>
                          ) : field.type === 'number' ? (
                            <input
                              type="number"
                              value={mechanic?.config[field.key] ?? field.default}
                              onChange={(e) => updateCoreMechanicConfig(type as CoreMechanicType, field.key, parseFloat(e.target.value) || 0)}
                              className="w-full px-2 py-1 border border-slate-200 rounded text-sm"
                            />
                          ) : (
                            <input
                              type="text"
                              value={mechanic?.config[field.key] || ''}
                              onChange={(e) => updateCoreMechanicConfig(type as CoreMechanicType, field.key, e.target.value)}
                              className="w-full px-2 py-1 border border-slate-200 rounded text-sm"
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Select Actions */}
      <div className="border border-slate-200 rounded-lg p-4">
        <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center gap-2">
          <Zap size={16} />
          {t('templateBuilder.selectActions', { defaultValue: 'Select Actions' })}
        </h3>
        <p className="text-xs text-slate-500 mb-4">
          {t('templateBuilder.selectActionsHint', { defaultValue: 'Choose which actions agents can perform in this simulation.' })}
        </p>
        <p className="text-xs text-amber-600 mb-4">
          {t('templateBuilder.mechanicAutoEnabled', { defaultValue: 'Required for selected actions' })}
        </p>

        <div className="space-y-4">
          {ACTION_CATEGORIES.map(category => {
            const categoryActions = actionsByCategory[category];
            if (!categoryActions || categoryActions.length === 0) return null;

            return (
              <div key={category} className="border border-slate-200 rounded-lg p-3 bg-slate-50">
                <h4 className="text-xs font-bold text-slate-700 uppercase tracking-wide mb-2">
                  {t(`templateBuilder.categories.${category}`, { defaultValue: category })}
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {categoryActions.map(action => {
                    const isSelected = isActionSelected(action.id);
                    const requiredMechanics = ACTION_MECHANIC_REQUIREMENTS[action.id] || [];
                    const autoEnabledMechs = requiredMechanics.filter(
                      m => !template.coreMechanics.find(cm => cm.type === m)?.enabled
                    );

                    return (
                      <label key={action.id} className="flex items-start gap-2 cursor-pointer hover:bg-white p-1.5 rounded transition-colors">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={(e) => toggleAction(action.id, e.target.checked)}
                          className="w-4 h-4 text-brand-600 rounded focus:ring-brand-500 mt-0.5"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium text-slate-700">{action.id}</div>
                          <div className="text-xs text-slate-500">{t(`templateBuilder.actions.${action.id}`, { defaultValue: action.id })}</div>
                          {autoEnabledMechs.length > 0 && (
                            <div className="text-xs text-amber-600 mt-0.5">
                              {autoEnabledMechs.map(m =>
                                t(`templateBuilder.mechanics.${m}`, { defaultValue: m })
                              ).join(', ')}
                            </div>
                          )}
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
          <span>
            {t('templateBuilder.selectedCount', { defaultValue: '{{count}} selected' }).replace('{{count}}', String(template.availableActions?.length || 0))}
          </span>
          <button
            onClick={() => updateTemplate({ availableActions: [] })}
            className="text-red-500 hover:text-red-700"
          >
            {t('templateBuilder.clearAll', { defaultValue: 'Clear All' })}
          </button>
        </div>
      </div>

      {/* Environment */}
      <div className="border border-slate-200 rounded-lg p-4">
        <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center gap-2">
          <Globe size={16} />
          {t('templateBuilder.environment', { defaultValue: 'Environment' })}
        </h3>
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              {t('templateBuilder.environmentDescription', { defaultValue: 'Environment Description' })}
            </label>
            <textarea
              value={template.environment.description}
              onChange={(e) => updateEnvironment('description', e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-500 outline-none resize-none"
              rows={3}
              placeholder={t('templateBuilder.placeholders.environment', { defaultValue: 'Describe the simulation environment...' })}
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-xs font-medium text-slate-600">
                {t('templateBuilder.environmentRules', { defaultValue: 'Environment Rules' })}
              </label>
              <button
                onClick={addEnvironmentRule}
                className="text-xs px-2 py-1 bg-slate-100 text-slate-600 rounded hover:bg-slate-200 flex items-center gap-1"
              >
                <Plus size={12} />
                {t('templateBuilder.addRule', { defaultValue: 'Add Rule' })}
              </button>
            </div>
            <div className="space-y-2">
              {(!template.environment.rules || template.environment.rules.length === 0) ? (
                <div className="text-center py-2 text-slate-400 text-sm bg-slate-50 rounded border border-dashed border-slate-200">
                  {t('templateBuilder.noRules', { defaultValue: 'No rules defined' })}
                </div>
              ) : (
                template.environment.rules.map((rule, index) => (
                  <div key={index} className="flex items-center gap-2">
                    <span className="text-xs text-slate-500">{index + 1}.</span>
                    <input
                      type="text"
                      value={rule}
                      onChange={(e) => updateEnvironmentRule(index, e.target.value)}
                      className="flex-1 px-2 py-1 border border-slate-200 rounded text-sm"
                      placeholder={t('templateBuilder.rulePlaceholder', { defaultValue: 'Enter a rule...' })}
                    />
                    <button
                      onClick={() => removeEnvironmentRule(index)}
                      className="p-1 text-red-500 hover:bg-red-50 rounded"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Time Configuration */}
      {onTimeConfigChange && timeConfig && (
        <div className="border border-slate-200 rounded-lg p-4">
          <h3 className="text-sm font-bold text-slate-800 mb-4">
            {t('templateBuilder.timeConfig', { defaultValue: 'Time Configuration' })}
          </h3>
          <div className="flex gap-4">
            <div className="flex-1">
              <label className="block text-xs text-slate-600 mb-1">{t('templateBuilder.baseTime', { defaultValue: 'Base Time' })}</label>
              <input
                type="datetime-local"
                value={timeConfig.baseTime.slice(0, 16)}
                onChange={(e) => updateTimeConfig('baseTime', new Date(e.target.value).toISOString())}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
              />
            </div>
            <div className="flex-1">
              <label className="block text-xs text-slate-600 mb-1">{t('templateBuilder.timeUnit', { defaultValue: 'Time Unit' })}</label>
              <select
                value={timeConfig.unit}
                onChange={(e) => updateTimeConfig('unit', e.target.value as TimeUnit)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
              >
                {TIME_UNITS.map(u => (
                  <option key={u.value} value={u.value}>{t(`wizard.timeUnits.${u.value}`)}</option>
                ))}
              </select>
            </div>
            <div className="w-24">
              <label className="block text-xs text-slate-600 mb-1">{t('templateBuilder.timeStep', { defaultValue: 'Step' })}</label>
              <input
                type="number"
                min="1"
                value={timeConfig.step}
                onChange={(e) => updateTimeConfig('step', parseInt(e.target.value) || 1)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export const createEmptyGenericTemplate = (): GenericTemplateConfig => ({
  id: generateId(),
  name: '',
  description: '',
  version: '1.0.0',
  coreMechanics: [
    createEmptyCoreMechanic('grid'),
    createEmptyCoreMechanic('discussion'),
    createEmptyCoreMechanic('voting'),
    createEmptyCoreMechanic('resources'),
    createEmptyCoreMechanic('hierarchy'),
    createEmptyCoreMechanic('time')
  ],
  availableActions: [],
  environment: {
    description: '',
    rules: []
  },
  defaultTimeConfig: {
    baseTime: new Date().toISOString(),
    unit: 'hour',
    step: 1
  }
});
