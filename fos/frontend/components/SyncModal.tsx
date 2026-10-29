import React from 'react';
import { useSimulationStore } from '../store';
import { useTranslation } from 'react-i18next';
import { X, DownloadCloud, Loader2 } from 'lucide-react';

export const SyncModal: React.FC = () => {
  const { t } = useTranslation();
  const isOpen = useSimulationStore((s) => s.isSyncModalOpen);
  const close = useSimulationStore((s) => s.closeSyncModal);
  const sync = useSimulationStore((s) => s.syncCurrentSimulation);
  const logs = useSimulationStore((s) => s.syncLogs);
  const isSyncing = useSimulationStore((s) => s.isSyncing);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[70vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <div className="flex items-center gap-2">
            <DownloadCloud />
            <div className="font-bold">{t('components.syncModal.title')}</div>
          </div>
          <div className="flex items-center gap-2">
            <button className="text-sm text-slate-500 hover:text-slate-700" onClick={() => { if (!isSyncing) close(); }}>
              <X />
            </button>
          </div>
        </div>

        <div className="p-4 flex-1 overflow-auto">
          <div className="text-sm text-slate-600 mb-3">{t('components.syncModal.syncLogs')}</div>
          <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-3">
            {t('components.syncModal.warningMessage')}
          </div>
          <div className="bg-slate-100 rounded p-3 h-64 overflow-auto font-mono text-xs">
            {(logs && logs.length) ? (
              logs.map((l, i) => (
                <div key={i} className={l.startsWith('[ERROR]') ? 'text-red-600' : l.startsWith('[OK]') ? 'text-emerald-700' : 'text-slate-700'}>
                  {l}
                </div>
              ))
            ) : (
              <div className="text-slate-400">{t('components.syncModal.noLogsYet')}</div>
            )}
          </div>
        </div>

        <div className="p-4 border-t flex items-center justify-end gap-2">
          <button
            onClick={() => {
              try {
                const text = (logs || []).join('\n');
                navigator.clipboard.writeText(text || '');
                // small visual feedback
                alert(t('components.syncModal.copiedToClipboard'));
              } catch (e) {
                alert(t('components.syncModal.copyFailed'));
              }
            }}
            className="px-3 py-2 rounded border text-sm"
          >{t('components.syncModal.copyLogs')}</button>
          <button
            onClick={() => {
              const content = (logs || []).join('\n');
              const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = `sync-log-${Date.now()}.txt`;
              document.body.appendChild(a);
              a.click();
              a.remove();
              URL.revokeObjectURL(url);
            }}
            className="px-3 py-2 rounded border text-sm"
          >{t('components.syncModal.downloadLogs')}</button>
          <button
            onClick={() => {
              if (isSyncing) return;
              const ok = window.confirm(t('components.syncModal.confirmSaveBackend'));
              if (!ok) return;
              sync();
            }}
            className={`px-4 py-2 rounded text-sm font-medium ${isSyncing ? 'bg-slate-300 text-slate-700 cursor-wait' : 'bg-brand-600 text-white hover:bg-brand-700'}`}
            disabled={isSyncing}
          >
            {isSyncing ? (
              <span className="flex items-center gap-2"><Loader2 className="animate-spin" size={14} /> {t('components.syncModal.syncing')}</span>
            ) : (
              <span className="flex items-center gap-2"><DownloadCloud size={14} /> {t('components.syncModal.startSync')}</span>
            )}
          </button>
          <button onClick={() => { if (!isSyncing) close(); }} className="px-4 py-2 rounded border text-sm">{t('components.syncModal.close')}</button>
        </div>
      </div>
    </div>
  );
};

export default SyncModal;
