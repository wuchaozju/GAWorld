import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Settings,
  Plus,
  Trash2,
  X,
  ChevronDown,
  ChevronUp,
  Check,
  AlertTriangle,
} from 'lucide-react';

export interface RuleCondition {
  field: string;
  operator: 'eq' | 'ne' | 'gt' | 'ge' | 'lt' | 'le' | 'in' | 'not_in' | 'contains';
  value: string | number | boolean | string[];
}

export interface RuleAction {
  event_type: 'policy' | 'market' | 'news' | 'custom' | 'manual';
  severity: 'low' | 'medium' | 'high' | 'critical';
  title_template: string;
  content_template: string;
}

export interface Rule {
  id: string;
  name: string;
  description: string;
  conditions: RuleCondition[];
  action: RuleAction;
  enabled: boolean;
  cooldown_seconds: number;
}

interface RuleConfigProps {
  rules: Rule[];
  onChange: (rules: Rule[]) => void;
  simulationId?: string;
}

const operators = [
  { value: 'eq', label: 'equals' },
  { value: 'ne', label: 'not equals' },
  { value: 'gt', label: 'greater than' },
  { value: 'ge', label: 'greater or equal' },
  { value: 'lt', label: 'less than' },
  { value: 'le', label: 'less or equal' },
  { value: 'in', label: 'in list' },
  { value: 'not_in', label: 'not in list' },
  { value: 'contains', label: 'contains' },
] as const;

const eventTypes = ['policy', 'market', 'news', 'custom', 'manual'] as const;
const severityLevels = ['low', 'medium', 'high', 'critical'] as const;

function RuleCard({
  rule,
  onUpdate,
  onDelete,
}: {
  rule: Rule;
  onUpdate: (rule: Rule) => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const updateCondition = (index: number, field: string, value: unknown) => {
    const newConditions = rule.conditions.map((c, i) =>
      i === index ? { ...c, [field]: value } : c
    );
    onUpdate({ ...rule, conditions: newConditions });
  };

  const addCondition = () => {
    onUpdate({
      ...rule,
      conditions: [
        ...rule.conditions,
        { field: 'resource_pressure', operator: 'gt' as const, value: 0.8 },
      ],
    });
  };

  const removeCondition = (index: number) => {
    onUpdate({
      ...rule,
      conditions: rule.conditions.filter((_, i) => i !== index),
    });
  };

  return (
    <div className={`border rounded-lg ${rule.enabled ? 'bg-white' : 'bg-gray-50'}`}>
      <div className="p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => onUpdate({ ...rule, enabled: !rule.enabled })}
            className={`w-10 h-6 rounded-full transition-colors ${
              rule.enabled ? 'bg-indigo-600' : 'bg-gray-300'
            }`}
          >
            <div
              className={`w-4 h-4 rounded-full bg-white shadow transform transition-transform ${
                rule.enabled ? 'translate-x-5' : 'translate-x-1'
              }`}
            />
          </button>
          <div>
            <h4 className="font-medium text-gray-900">{rule.name}</h4>
            <p className="text-xs text-gray-500">
              {rule.conditions.length} condition(s) • {rule.cooldown_seconds}s cooldown
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1 text-gray-400 hover:text-gray-600"
          >
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
          <button onClick={onDelete} className="p-1 text-red-400 hover:text-red-600">
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {expanded && (
        <div className="p-4 border-t space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('components.rule.config.name')}
            </label>
            <input
              type="text"
              value={rule.name}
              onChange={(e) => onUpdate({ ...rule, name: e.target.value })}
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('components.rule.config.description')}
            </label>
            <input
              type="text"
              value={rule.description}
              onChange={(e) => onUpdate({ ...rule, description: e.target.value })}
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('components.rule.config.conditions')}
            </label>
            <div className="space-y-2">
              {rule.conditions.map((condition, index) => (
                <div key={index} className="flex items-center gap-2">
                  <input
                    type="text"
                    value={condition.field}
                    onChange={(e) => updateCondition(index, 'field', e.target.value)}
                    placeholder="field.path"
                    className="flex-1 px-2 py-1 border rounded text-sm"
                  />
                  <select
                    value={condition.operator}
                    onChange={(e) => updateCondition(index, 'operator', e.target.value)}
                    className="px-2 py-1 border rounded text-sm"
                  >
                    {operators.map((op) => (
                      <option key={op.value} value={op.value}>
                        {op.label}
                      </option>
                    ))}
                  </select>
                  <input
                    type="text"
                    value={String(condition.value)}
                    onChange={(e) => updateCondition(index, 'value', e.target.value)}
                    placeholder="value"
                    className="flex-1 px-2 py-1 border rounded text-sm"
                  />
                  <button
                    onClick={() => removeCondition(index)}
                    className="p-1 text-red-400 hover:text-red-600"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
              <button
                onClick={addCondition}
                className="flex items-center gap-1 text-sm text-indigo-600 hover:text-indigo-700"
              >
                <Plus className="w-4 h-4" />
                {t('components.rule.config.addCondition')}
              </button>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('components.rule.config.cooldown')}
            </label>
            <input
              type="number"
              value={rule.cooldown_seconds}
              onChange={(e) =>
                onUpdate({ ...rule, cooldown_seconds: parseInt(e.target.value) || 300 })
              }
              className="w-full px-3 py-2 border rounded-lg text-sm"
              min={0}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t('components.rule.config.eventType')}
              </label>
              <select
                value={rule.action.event_type}
                onChange={(e) =>
                  onUpdate({
                    ...rule,
                    action: { ...rule.action, event_type: e.target.value as typeof eventTypes[number] },
                  })
                }
                className="w-full px-3 py-2 border rounded-lg text-sm"
              >
                {eventTypes.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t('components.rule.config.severity')}
              </label>
              <select
                value={rule.action.severity}
                onChange={(e) =>
                  onUpdate({
                    ...rule,
                    action: { ...rule.action, severity: e.target.value as typeof severityLevels[number] },
                  })
                }
                className="w-full px-3 py-2 border rounded-lg text-sm"
              >
                {severityLevels.map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('components.rule.config.titleTemplate')}
            </label>
            <input
              type="text"
              value={rule.action.title_template}
              onChange={(e) =>
                onUpdate({
                  ...rule,
                  action: { ...rule.action, title_template: e.target.value },
                })
              }
              className="w-full px-3 py-2 border rounded-lg text-sm"
              placeholder="{field_name} triggered"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('components.rule.config.contentTemplate')}
            </label>
            <textarea
              value={rule.action.content_template}
              onChange={(e) =>
                onUpdate({
                  ...rule,
                  action: { ...rule.action, content_template: e.target.value },
                })
              }
              className="w-full px-3 py-2 border rounded-lg text-sm"
              rows={2}
              placeholder="Condition {field_name} was met"
            />
          </div>
        </div>
      )}
    </div>
  );
}

export const RuleConfig: React.FC<RuleConfigProps> = ({ rules, onChange, simulationId }) => {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  // Load rules from backend on mount, save on change
  React.useEffect(() => {
    if (!simulationId) return;
    (async () => {
      const { apiClient } = await import('../services/client');
      try {
        const resp = await apiClient.get(`/rules?simulation_id=${simulationId}`);
        const backendRules = resp.data?.rules || [];
        if (backendRules.length > 0) {
          onChange(backendRules);
        }
      } catch (e) {
        // Silently ignore — local state is fine for MVP
      }
    })();
  }, [simulationId]);

  // Debounced auto-save to backend
  React.useEffect(() => {
    if (!simulationId || rules.length === 0) return;
    const timer = setTimeout(async () => {
      const { apiClient } = await import('../services/client');
      try {
        await apiClient.post(`/rules?simulation_id=${simulationId}`, { rules });
      } catch (e) {
        console.warn('Failed to save rules to backend', e);
      }
    }, 1000);
    return () => clearTimeout(timer);
  }, [rules, simulationId]);

  const addRule = () => {
    const newRule: Rule = {
      id: `rule-${Date.now()}`,
      name: t('components.rule.config.newRule'),
      description: '',
      conditions: [{ field: 'resource_pressure', operator: 'gt', value: 0.8 }],
      action: {
        event_type: 'market',
        severity: 'high',
        title_template: 'Resource Alert',
        content_template: 'Resource pressure exceeded threshold',
      },
      enabled: true,
      cooldown_seconds: 300,
    };
    onChange([...rules, newRule]);
  };

  const updateRule = (index: number, updatedRule: Rule) => {
    const newRules = [...rules];
    newRules[index] = updatedRule;
    onChange(newRules);
  };

  const deleteRule = (index: number) => {
    onChange(rules.filter((_, i) => i !== index));
  };

  return (
    <div className="border rounded-lg bg-white shadow-sm">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-4 flex items-center justify-between hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Settings className="w-5 h-5 text-indigo-600" />
          <h3 className="font-medium text-gray-900">{t('components.rule.config.title')}</h3>
          <span className="text-xs text-gray-500">({rules.length})</span>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>

      {expanded && (
        <div className="border-t p-4 space-y-3">
          {rules.length === 0 ? (
            <div className="text-center py-6 text-gray-500">
              <Settings className="w-8 h-8 mx-auto mb-2 text-gray-300" />
              <p className="text-sm">{t('components.rule.config.noRules')}</p>
              <p className="text-xs text-gray-400 mt-1">{t('components.rule.config.noRulesHint')}</p>
            </div>
          ) : (
            rules.map((rule, index) => (
              <RuleCard
                key={rule.id}
                rule={rule}
                onUpdate={(updated) => updateRule(index, updated)}
                onDelete={() => deleteRule(index)}
              />
            ))
          )}

          <button
            onClick={addRule}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 border-2 border-dashed border-gray-300 rounded-lg text-gray-600 hover:border-indigo-600 hover:text-indigo-600 transition-colors"
          >
            <Plus className="w-4 h-4" />
            {t('components.rule.config.addRule')}
          </button>
        </div>
      )}
    </div>
  );
};

export default RuleConfig;