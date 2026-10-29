import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Settings,
  Plus,
  Pencil,
  Trash2,
  Pause,
  Play,
  RefreshCw,
  Globe,
  Loader2,
  X,
} from 'lucide-react';
import { dataSourceApi, DataSource } from '../services/dataSourceApi';
import { AddDataSourceModal } from './AddDataSourceModal';

export const DataSourceSettings: React.FC = () => {
  const { t } = useTranslation();
  const [sources, setSources] = useState<DataSource[]>([]);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [editSource, setEditSource] = useState<DataSource | null>(null);
  const [pollingId, setPollingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchSources = async () => {
    setLoading(true);
    try {
      const response = await dataSourceApi.list();
      const list = response.data?.data_sources ?? response.data ?? [];
      setSources(Array.isArray(list) ? list : []);
    } catch (e) {
      console.warn('Failed to fetch data sources', e);
      setError(t('settings.dataSource.message.operationFailed'));
      setTimeout(() => setError(null), 3000);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSources();
    const interval = setInterval(fetchSources, 30 * 1000);
    return () => clearInterval(interval);
  }, []);

  const handleDelete = async (id: string) => {
    if (!confirm(t('settings.dataSource.confirm.deleteMessage'))) return;
    try {
      await dataSourceApi.delete(id);
      fetchSources();
    } catch (e) {
      console.warn('Failed to delete data source', e);
      setError(t('settings.dataSource.message.operationFailed'));
      setTimeout(() => setError(null), 3000);
    }
  };

  const handlePauseResume = async (source: DataSource) => {
    try {
      await dataSourceApi.update(source.id, { is_enabled: !source.is_enabled });
      fetchSources();
    } catch (e) {
      console.warn('Failed to pause/resume data source', e);
      setError(t('settings.dataSource.message.operationFailed'));
      setTimeout(() => setError(null), 3000);
    }
  };

  const handlePoll = async (id: string) => {
    setPollingId(id);
    try {
      await dataSourceApi.poll(id);
      // Poll is async, just show loading briefly then refresh
      setTimeout(fetchSources, 1000);
    } catch (e) {
      console.warn('Failed to trigger poll', e);
      setError(t('settings.dataSource.message.operationFailed'));
      setTimeout(() => setError(null), 3000);
    } finally {
      setPollingId(null);
    }
  };

  const handleEdit = (source: DataSource) => {
    setEditSource(source);
    setShowModal(true);
  };

  const handleAdd = () => {
    setEditSource(null);
    setShowModal(true);
  };

  const handleModalClose = () => {
    setShowModal(false);
    setEditSource(null);
    fetchSources();
  };

  const getStatusBadge = (source: DataSource) => {
    if (!source.is_enabled) {
      return <span className="px-2 py-0.5 text-xs rounded bg-gray-100 text-gray-600">{t('settings.dataSource.status.paused')}</span>;
    }
    if (source.last_error) {
      return <span className="px-2 py-0.5 text-xs rounded bg-red-50 text-red-600">{t('settings.dataSource.status.error')}</span>;
    }
    return <span className="px-2 py-0.5 text-xs rounded bg-green-50 text-green-600">{t('settings.dataSource.status.running')}</span>;
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-medium">{t('settings.dataSource.title')}</h2>
        <button
          onClick={handleAdd}
          className="flex items-center gap-1 px-3 py-1.5 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700"
        >
          <Plus className="w-4 h-4" />
          {t('settings.dataSource.addTitle')}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">
          {error}
        </div>
      )}

      {sources.length === 0 && !loading ? (
        <div className="text-center py-12 text-gray-500">
          <Globe className="w-8 h-8 mx-auto mb-2 text-gray-300" />
          <p>{t('settings.dataSource.empty')}</p>
          <p className="text-xs text-gray-400 mt-1">{t('settings.dataSource.emptyHint')}</p>
        </div>
      ) : (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-2 font-medium text-gray-600">{t('settings.dataSource.table.name')}</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">{t('settings.dataSource.table.eventType')}</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">{t('settings.dataSource.table.pollInterval')}</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">{t('settings.dataSource.table.status')}</th>
                <th className="text-right px-4 py-2 font-medium text-gray-600">{t('settings.dataSource.table.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {sources.map(source => (
                <tr key={source.id} className="border-b last:border-b-0 hover:bg-gray-50">
                  <td className="px-4 py-2 font-medium text-gray-900">{source.name}</td>
                  <td className="px-4 py-2 text-gray-600">{t(`dataSource.table.eventType${source.event_type.charAt(0).toUpperCase() + source.event_type.slice(1)}`) || source.event_type}</td>
                  <td className="px-4 py-2 text-gray-600">{source.poll_interval_seconds}{t('settings.dataSource.table.seconds')}</td>
                  <td className="px-4 py-2">{getStatusBadge(source)}</td>
                  <td className="px-4 py-2">
                    <div className="flex items-center justify-end gap-1">
                      <button onClick={() => handlePoll(source.id)} disabled={pollingId === source.id} className="p-1.5 text-gray-500 hover:text-indigo-600" title={t('settings.dataSource.actions.poll')}>
                        {pollingId === source.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                      </button>
                      <button onClick={() => handleEdit(source)} className="p-1.5 text-gray-500 hover:text-indigo-600" title={t('settings.dataSource.actions.edit')}>
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button onClick={() => handlePauseResume(source)} className="p-1.5 text-gray-500 hover:text-indigo-600" title={source.is_enabled ? t('settings.dataSource.actions.pause') : t('settings.dataSource.actions.resume')}>
                        {source.is_enabled ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                      </button>
                      <button onClick={() => handleDelete(source.id)} className="p-1.5 text-gray-500 hover:text-red-600" title={t('settings.dataSource.actions.delete')}>
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <AddDataSourceModal
          source={editSource}
          onClose={handleModalClose}
        />
      )}
    </div>
  );
};