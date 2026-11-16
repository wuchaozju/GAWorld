import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X, ChevronDown } from 'lucide-react';
import { dataSourceApi, DataSource } from '../services/dataSourceApi';
import { DATA_SOURCE_TEMPLATES, TEMPLATE_CATEGORIES } from '../services/dataSourceTemplates';

interface AddDataSourceModalProps {
  source?: DataSource | null;
  onClose: () => void;
}

export const AddDataSourceModal: React.FC<AddDataSourceModalProps> = ({ source, onClose }) => {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [showTemplates, setShowTemplates] = useState(!source);
  const [form, setForm] = useState({
    name: source?.name || '',
    api_url: source?.api_url || '',
    auth_type: source?.auth_type || 'none',
    auth_token: source?.auth_token || '',
    poll_interval_seconds: source?.poll_interval_seconds || 300,
    event_type: source?.event_type || 'market',
    is_global: source?.is_global ?? true,
    simulation_id: source?.simulation_id || '',
    field_mapping: source?.field_mapping || { title_path: '', content_path: '', timestamp_path: '', url_path: '' },
    is_enabled: source?.is_enabled ?? true,
  });

  const applyTemplate = (templateId: string) => {
    const tmpl = DATA_SOURCE_TEMPLATES.find(t => t.id === templateId);
    if (!tmpl) return;
    setForm(f => ({
      ...f,
      name: tmpl.defaults.name,
      api_url: tmpl.defaults.api_url,
      auth_type: tmpl.defaults.auth_type,
      auth_token: tmpl.defaults.auth_token || '',
      poll_interval_seconds: tmpl.defaults.poll_interval_seconds,
      event_type: tmpl.defaults.event_type,
      field_mapping: { ...tmpl.defaults.field_mapping },
    }));
    setShowTemplates(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.api_url.trim()) return;

    setSaving(true);
    setSaveError(null);
    try {
      const raw = parseInt(String(form.poll_interval_seconds), 10);
      if (isNaN(raw) || raw < 60 || raw > 86400) {
        setSaveError(t('settings.dataSource.message.invalidPollInterval'));
        setSaving(false);
        return;
      }
      const payload = {
        ...form,
        simulation_id: form.is_global ? null : (form.simulation_id || null),
        poll_interval_seconds: raw,
        field_mapping: form.field_mapping,
      };

      if (source?.id) {
        await dataSourceApi.update(source.id, payload);
      } else {
        await dataSourceApi.create(payload);
      }
      onClose();
    } catch (e) {
      console.warn('Failed to save data source', e);
      setSaveError(t('settings.dataSource.message.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="text-lg font-medium">{source ? t('settings.dataSource.editTitle') : t('settings.dataSource.addTitle')}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {!source && (
          <div className="px-4 pt-3">
            <button
              type="button"
              onClick={() => setShowTemplates(v => !v)}
              className="flex items-center gap-1 text-sm text-indigo-600 hover:text-indigo-700 font-medium"
            >
              <ChevronDown className={`w-4 h-4 transition-transform ${showTemplates ? 'rotate-180' : ''}`} />
              {showTemplates ? t('settings.dataSource.form.hideTemplates') : t('settings.dataSource.form.browseTemplates')}
            </button>
          </div>
        )}

        {showTemplates && !source && (
          <div className="px-4 pb-2 max-h-64 overflow-y-auto">
            <div className="grid grid-cols-2 gap-2">
              {TEMPLATE_CATEGORIES.map(cat => {
                const catTemplates = DATA_SOURCE_TEMPLATES.filter(t => t.category === cat.id);
                if (catTemplates.length === 0) return null;
                return (
                  <div key={cat.id} className="space-y-1">
                    <p className="text-xs font-medium text-gray-400 uppercase">{t(cat.labelKey)}</p>
                    {catTemplates.map(tmpl => (
                      <button
                        key={tmpl.id}
                        type="button"
                        onClick={() => applyTemplate(tmpl.id)}
                        className="w-full text-left px-3 py-2 rounded border hover:border-indigo-400 hover:bg-indigo-50 transition-colors"
                      >
                        <span className="text-sm">{tmpl.icon} {t(tmpl.nameKey)}</span>
                        <p className="text-xs text-gray-500 mt-0.5">{t(tmpl.descriptionKey)}</p>
                      </button>
                    ))}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('settings.dataSource.form.name')} *</label>
            <input
              type="text"
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              className="w-full border rounded px-3 py-2 text-sm focus:ring-1 focus:ring-indigo-500 outline-none"
              required
            />
          </div>

          {/* API URL */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('settings.dataSource.form.apiUrl')} *</label>
            <input
              type="url"
              value={form.api_url}
              onChange={e => setForm(f => ({ ...f, api_url: e.target.value }))}
              placeholder="https://api.example.com/events"
              className="w-full border rounded px-3 py-2 text-sm focus:ring-1 focus:ring-indigo-500 outline-none"
              required
            />
          </div>

          {/* Auth Type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('settings.dataSource.form.authType')}</label>
            <div className="flex gap-4">
              {(['none', 'bearer', 'api_key'] as const).map(type => (
                <label key={type} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="radio"
                    name="auth_type"
                    value={type}
                    checked={form.auth_type === type}
                    onChange={e => setForm(f => ({ ...f, auth_type: e.target.value as typeof form.auth_type }))}
                  />
                  {t(`dataSource.form.auth${type.charAt(0).toUpperCase() + type.slice(1).replace('_', '')}`)}
                </label>
              ))}
            </div>
          </div>

          {/* Auth Token */}
          {(form.auth_type === 'bearer' || form.auth_type === 'api_key') && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('settings.dataSource.form.authToken')}</label>
              <input
                type="password"
                value={form.auth_token}
                onChange={e => setForm(f => ({ ...f, auth_token: e.target.value }))}
                className="w-full border rounded px-3 py-2 text-sm focus:ring-1 focus:ring-indigo-500 outline-none"
                placeholder="••••••••"
              />
            </div>
          )}

          {/* Poll Interval */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('settings.dataSource.form.pollInterval')}</label>
            <input
              type="number"
              value={form.poll_interval_seconds}
              onChange={e => {
                const raw = parseInt(e.target.value, 10);
                if (!isNaN(raw) && raw >= 60 && raw <= 86400) {
                  setForm(f => ({ ...f, poll_interval_seconds: raw }));
                }
              }}
              min={60}
              max={86400}
              className="w-full border rounded px-3 py-2 text-sm focus:ring-1 focus:ring-indigo-500 outline-none"
            />
          </div>

          {/* Event Type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('settings.dataSource.form.eventType')}</label>
            <select
              value={form.event_type}
              onChange={e => setForm(f => ({ ...f, event_type: e.target.value }))}
              className="w-full border rounded px-3 py-2 text-sm focus:ring-1 focus:ring-indigo-500 outline-none bg-white"
            >
              <option value="market">{t('settings.dataSource.form.eventTypeMarket')}</option>
              <option value="policy">{t('settings.dataSource.form.eventTypePolicy')}</option>
              <option value="news">{t('settings.dataSource.form.eventTypeNews')}</option>
              <option value="custom">{t('settings.dataSource.form.eventTypeCustom')}</option>
            </select>
          </div>

          {/* Scope */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('settings.dataSource.form.scope')}</label>
            <div className="flex gap-4">
              <label className="flex items-center gap-1.5 text-sm">
                <input
                  type="radio"
                  name="is_global"
                  value="true"
                  checked={form.is_global === true}
                  onChange={() => setForm(f => ({ ...f, is_global: true }))}
                />
                {t('settings.dataSource.form.scopeGlobal')}
              </label>
              <label className="flex items-center gap-1.5 text-sm">
                <input
                  type="radio"
                  name="is_global"
                  value="false"
                  checked={form.is_global === false}
                  onChange={() => setForm(f => ({ ...f, is_global: false }))}
                />
                {t('settings.dataSource.form.scopeSimulation')}
              </label>
            </div>
          </div>

          {/* Simulation ID (shown when is_global is false) */}
          {!form.is_global && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('settings.dataSource.form.simulationId')}</label>
              <input
                type="text"
                value={form.simulation_id}
                onChange={e => setForm(f => ({ ...f, simulation_id: e.target.value }))}
                className="w-full border rounded px-3 py-2 text-sm focus:ring-1 focus:ring-indigo-500 outline-none"
              />
            </div>
          )}

          {/* Field Mapping */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">{t('settings.dataSource.form.fieldMapping')}</label>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-gray-500 block mb-0.5">{t('settings.dataSource.form.titleField')}</label>
                <input
                  type="text"
                  value={form.field_mapping.title_path || ''}
                  onChange={e => setForm(f => ({ ...f, field_mapping: { ...f.field_mapping, title_path: e.target.value } }))}
                  placeholder="data.items[].title"
                  className="w-full border rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-indigo-500 outline-none"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-0.5">{t('settings.dataSource.form.contentField')}</label>
                <input
                  type="text"
                  value={form.field_mapping.content_path || ''}
                  onChange={e => setForm(f => ({ ...f, field_mapping: { ...f.field_mapping, content_path: e.target.value } }))}
                  placeholder="data.items[].content"
                  className="w-full border rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-indigo-500 outline-none"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-0.5">{t('settings.dataSource.form.timestampField')}</label>
                <input
                  type="text"
                  value={form.field_mapping.timestamp_path || ''}
                  onChange={e => setForm(f => ({ ...f, field_mapping: { ...f.field_mapping, timestamp_path: e.target.value } }))}
                  placeholder="data.items[].timestamp"
                  className="w-full border rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-indigo-500 outline-none"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-0.5">{t('settings.dataSource.form.urlField')}</label>
                <input
                  type="text"
                  value={form.field_mapping.url_path || ''}
                  onChange={e => setForm(f => ({ ...f, field_mapping: { ...f.field_mapping, url_path: e.target.value } }))}
                  placeholder="data.items[].url"
                  className="w-full border rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-indigo-500 outline-none"
                />
              </div>
            </div>
          </div>

          {saveError && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
              {saveError}
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-2 border-t">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50 transition-colors"
            >
              {t('settings.dataSource.form.cancel')}
            </button>
            <button
              type="submit"
              disabled={saving || !form.name.trim() || !form.api_url.trim()}
              className="px-5 py-2 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {saving ? '...' : t('settings.dataSource.form.save')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};