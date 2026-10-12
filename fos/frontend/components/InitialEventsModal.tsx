import React, { useState } from 'react';
import { useSimulationStore } from '../store';
import { useTranslation } from 'react-i18next';
import { X, Plus, Save, Image as ImageIcon, Music2, Video } from 'lucide-react';
import { MultimodalInput } from './MultimodalInput';

export const InitialEventsModal: React.FC = () => {
  const { t } = useTranslation();
  const isOpen = useSimulationStore(s => (s as any).isInitialEventsOpen ?? false);
  const toggle = useSimulationStore(s => (s as any).toggleInitialEvents);
  const addInitialEvent = useSimulationStore(s => (s as any).addInitialEvent);
  const initialEvents = useSimulationStore(s => (s as any).initialEvents ?? []);

  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [mediaType, setMediaType] = useState<'image' | 'audio' | 'video' | null>(null);

  if (!isOpen) return null;

  const reset = () => {
    setTitle('');
    setContent('');
    setMediaUrl(null);
    setMediaType(null);
  };

  const handleSave = () => {
    if (!title && !content && !mediaUrl) return;
    addInitialEvent(
      title || t('components.initialEventsModal.defaultEventTitle'),
      content,
      mediaType === 'image' ? mediaUrl || undefined : undefined,
      mediaType === 'audio' ? mediaUrl || undefined : undefined,
      mediaType === 'video' ? mediaUrl || undefined : undefined,
    );
    reset();
  };

  return (
    <div className="ss-extension-modal">
      <div className="ss-extension-modal__panel ss-extension-modal__panel--wide h-[80vh]">
        <div className="ss-extension-modal__header">
          <div className="ss-extension-modal__header-title">
            <div className="ss-extension-modal__header-icon">
              <ImageIcon size={18} />
            </div>
            <div className="ss-extension-modal__header-copy">
              <h3>{t('components.initialEventsModal.title')}</h3>
            </div>
          </div>
          <button onClick={() => { toggle(false); reset(); }} className="text-slate-400 hover:text-slate-600"><X size={18} /></button>
        </div>

        <div className="ss-extension-modal__body space-y-4 bg-transparent">
          <div className="ss-extension-modal__surface p-3 space-y-3">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t('components.initialEventsModal.eventTitlePlaceholder')}
              className="w-full text-sm border rounded px-3 py-2 focus:ring-1 focus:ring-amber-500 outline-none"
            />
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder={t('components.initialEventsModal.eventDescPlaceholder')}
              className="w-full text-sm border rounded px-3 py-2 focus:ring-1 focus:ring-amber-500 outline-none min-h-[120px]"
            />
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="col-span-1">
                <MultimodalInput
                  label={t('components.initialEventsModal.imageOptional')}
                  helperText={t('components.initialEventsModal.uploadAutoInsert')}
                  enableCrop
                  onInsert={(url) => { setMediaUrl(url); setMediaType('image'); setContent((p) => `${p}${p ? '\n' : ''}![image](${url})`); }}
                />
              </div>
              <div className="col-span-1 space-y-2">
                <label className="text-xs font-bold text-slate-600 flex items-center gap-1"><Music2 size={14} /> {t('components.initialEventsModal.audioUrl')}</label>
                <input
                  type="url"
                  value={mediaType === 'audio' ? (mediaUrl || '') : ''}
                  onChange={(e) => { setMediaUrl(e.target.value); setMediaType('audio'); }}
                  placeholder={t('components.initialEventsModal.audioUrlPlaceholder')}
                  className="w-full text-sm border rounded px-3 py-2 focus:ring-1 focus:ring-amber-500 outline-none"
                />
              </div>
              <div className="col-span-1 space-y-2">
                <label className="text-xs font-bold text-slate-600 flex items-center gap-1"><Video size={14} /> {t('components.initialEventsModal.videoUrl')}</label>
                <input
                  type="url"
                  value={mediaType === 'video' ? (mediaUrl || '') : ''}
                  onChange={(e) => { setMediaUrl(e.target.value); setMediaType('video'); }}
                  placeholder={t('components.initialEventsModal.videoUrlPlaceholder')}
                  className="w-full text-sm border rounded px-3 py-2 focus:ring-1 focus:ring-amber-500 outline-none"
                />
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleSave}
                className="ss-extension-modal__action ss-extension-modal__action--primary flex-1 text-sm"
              >
                <Save size={14} /> {t('components.initialEventsModal.saveAndInject')}
              </button>
              <button
                onClick={reset}
                className="ss-extension-modal__action text-sm"
              >{t('components.initialEventsModal.reset')}</button>
            </div>
          </div>

          <div className="ss-extension-modal__surface p-3">
            <div className="text-xs font-bold text-slate-600 mb-2">{t('components.initialEventsModal.savedEvents')}</div>
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {initialEvents.length === 0 && <div className="text-xs text-slate-400">{t('components.initialEventsModal.noEventsYet')}</div>}
              {initialEvents.map(ev => (
                <div key={ev.id} className="border rounded p-2 text-sm bg-slate-50">
                  <div className="font-bold text-slate-700">{ev.title}</div>
                  <div className="text-slate-600 whitespace-pre-line text-xs">{ev.content}</div>
                  <div className="flex flex-wrap gap-2 mt-1 text-[11px] text-slate-500">
                    {ev.imageUrl && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-slate-100 rounded">
                        <ImageIcon size={12} /> {t('components.initialEventsModal.image')}
                      </span>
                    )}
                    {ev.audioUrl && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-slate-100 rounded">
                        <Music2 size={12} /> {t('components.initialEventsModal.audio')}
                      </span>
                    )}
                    {ev.videoUrl && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-slate-100 rounded">
                        <Video size={12} /> {t('components.initialEventsModal.video')}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
