import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Globe,
  Plus,
  Trash2,
  X,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Check,
  AlertCircle,
} from 'lucide-react';

export interface CustomAPIConfig {
  id: string;
  name: string;
  api_url: string;
  auth_type: 'none' | 'bearer' | 'apikey';
  auth_token: string;
  headers: Record<string, string>;
  field_mapping: {
    title: string;
    content: string;
    timestamp: string;
    severity: string;
  };
  poll_interval_minutes: number;
  enabled: boolean;
}

interface CustomAPIConfigPanelProps {
  configs: CustomAPIConfig[];
  onChange: (configs: CustomAPIConfig[]) => void;
}

function APICard({
  config,
  onUpdate,
  onDelete,
  onTest,
}: {
  config: CustomAPIConfig;
  onUpdate: (config: CustomAPIConfig) => void;
  onDelete: () => void;
  onTest: () => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<'success' | 'error' | null>(null);

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const response = await fetch(config.api_url, {
        method: 'GET',
        headers: {
          'User-Agent': 'Mozilla/5.0',
          'Accept': 'application/json',
          ...(config.auth_type === 'bearer' && config.auth_token
            ? { 'Authorization': `Bearer ${config.auth_token}` }
            : {}),
          ...(config.auth_type === 'apikey' && config.auth_token
            ? { 'X-API-Key': config.auth_token }
            : {}),
        },
      });
      setTestResult(response.ok ? 'success' : 'error');
    } catch {
      setTestResult('error');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className={`border rounded-lg ${config.enabled ? 'bg-white' : 'bg-gray-50'}`}>
      <div className="p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => onUpdate({ ...config, enabled: !config.enabled })}
            className={`w-10 h-6 rounded-full transition-colors ${
              config.enabled ? 'bg-indigo-600' : 'bg-gray-300'
            }`}
          >
            <div
              className={`w-4 h-4 rounded-full bg-white shadow transform transition-transform ${
                config.enabled ? 'translate-x-5' : 'translate-x-1'
              }`}
            />
          </button>
          <div>
            <h4 className="font-medium text-gray-900">{config.name}</h4>
            <p className="text-xs text-gray-500">{config.api_url}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleTest}
            disabled={testing}
            className="p-1 text-gray-400 hover:text-indigo-600 disabled:opacity-50"
            title={t('customApi.test')}
          >
            {testing ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : testResult === 'success' ? (
              <Check className="w-4 h-4 text-green-600" />
            ) : testResult === 'error' ? (
              <AlertCircle className="w-4 h-4 text-red-600" />
            ) : (
              <Globe className="w-4 h-4" />
            )}
          </button>
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
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t('customApi.name')}
              </label>
              <input
                type="text"
                value={config.name}
                onChange={(e) => onUpdate({ ...config, name: e.target.value })}
                className="w-full px-3 py-2 border rounded-lg text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t('customApi.pollInterval')}
              </label>
              <input
                type="number"
                value={config.poll_interval_minutes}
                onChange={(e) =>
                  onUpdate({ ...config, poll_interval_minutes: parseInt(e.target.value) || 10 })
                }
                className="w-full px-3 py-2 border rounded-lg text-sm"
                min={1}
                max={60}
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('customApi.apiUrl')}
            </label>
            <input
              type="url"
              value={config.api_url}
              onChange={(e) => onUpdate({ ...config, api_url: e.target.value })}
              placeholder="https://api.example.com/events"
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t('customApi.authType')}
              </label>
              <select
                value={config.auth_type}
                onChange={(e) =>
                  onUpdate({
                    ...config,
                    auth_type: e.target.value as 'none' | 'bearer' | 'apikey',
                  })
                }
                className="w-full px-3 py-2 border rounded-lg text-sm"
              >
                <option value="none">{t('customApi.authNone')}</option>
                <option value="bearer">{t('customApi.authBearer')}</option>
                <option value="apikey">{t('customApi.authApiKey')}</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t('customApi.authToken')}
              </label>
              <input
                type="password"
                value={config.auth_token}
                onChange={(e) => onUpdate({ ...config, auth_token: e.target.value })}
                placeholder={config.auth_type === 'none' ? '-' : '••••••••'}
                className="w-full px-3 py-2 border rounded-lg text-sm"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('customApi.fieldMapping')}
            </label>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-gray-500">{t('customApi.titleField')}</label>
                <input
                  type="text"
                  value={config.field_mapping.title}
                  onChange={(e) =>
                    onUpdate({
                      ...config,
                      field_mapping: { ...config.field_mapping, title: e.target.value },
                    })
                  }
                  className="w-full px-2 py-1 border rounded text-sm"
                  placeholder="title"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t('customApi.contentField')}</label>
                <input
                  type="text"
                  value={config.field_mapping.content}
                  onChange={(e) =>
                    onUpdate({
                      ...config,
                      field_mapping: { ...config.field_mapping, content: e.target.value },
                    })
                  }
                  className="w-full px-2 py-1 border rounded text-sm"
                  placeholder="content"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t('customApi.timestampField')}</label>
                <input
                  type="text"
                  value={config.field_mapping.timestamp}
                  onChange={(e) =>
                    onUpdate({
                      ...config,
                      field_mapping: { ...config.field_mapping, timestamp: e.target.value },
                    })
                  }
                  className="w-full px-2 py-1 border rounded text-sm"
                  placeholder="timestamp"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t('customApi.severityField')}</label>
                <input
                  type="text"
                  value={config.field_mapping.severity}
                  onChange={(e) =>
                    onUpdate({
                      ...config,
                      field_mapping: { ...config.field_mapping, severity: e.target.value },
                    })
                  }
                  className="w-full px-2 py-1 border rounded text-sm"
                  placeholder="severity"
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export const CustomAPIConfigPanel: React.FC<CustomAPIConfigPanelProps> = ({
  configs,
  onChange,
}) => {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const addConfig = () => {
    const newConfig: CustomAPIConfig = {
      id: `api-${Date.now()}`,
      name: t('customApi.newSource'),
      api_url: '',
      auth_type: 'none',
      auth_token: '',
      headers: {},
      field_mapping: {
        title: 'title',
        content: 'content',
        timestamp: 'timestamp',
        severity: 'severity',
      },
      poll_interval_minutes: 10,
      enabled: true,
    };
    onChange([...configs, newConfig]);
  };

  const updateConfig = (index: number, updated: CustomAPIConfig) => {
    const newConfigs = [...configs];
    newConfigs[index] = updated;
    onChange(newConfigs);
  };

  const deleteConfig = (index: number) => {
    onChange(configs.filter((_, i) => i !== index));
  };

  return (
    <div className="border rounded-lg bg-white shadow-sm">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-4 flex items-center justify-between hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Globe className="w-5 h-5 text-indigo-600" />
          <h3 className="font-medium text-gray-900">{t('customApi.title')}</h3>
          <span className="text-xs text-gray-500">({configs.length})</span>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>

      {expanded && (
        <div className="border-t p-4 space-y-3">
          {configs.length === 0 ? (
            <div className="text-center py-6 text-gray-500">
              <Globe className="w-8 h-8 mx-auto mb-2 text-gray-300" />
              <p className="text-sm">{t('customApi.noSources')}</p>
              <p className="text-xs text-gray-400 mt-1">{t('customApi.noSourcesHint')}</p>
            </div>
          ) : (
            configs.map((config, index) => (
              <APICard
                key={config.id}
                config={config}
                onUpdate={(updated) => updateConfig(index, updated)}
                onDelete={() => deleteConfig(index)}
                onTest={() => {}}
              />
            ))
          )}

          <button
            onClick={addConfig}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 border-2 border-dashed border-gray-300 rounded-lg text-gray-600 hover:border-indigo-600 hover:text-indigo-600 transition-colors"
          >
            <Plus className="w-4 h-4" />
            {t('customApi.addSource')}
          </button>
        </div>
      )}
    </div>
  );
};

export default CustomAPIConfigPanel;