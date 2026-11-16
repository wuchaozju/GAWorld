
import React, { useState } from 'react';
import { useSimulationStore } from '../store';
import { useTranslation } from 'react-i18next';
import { X, Save, LayoutTemplate } from 'lucide-react';
import { MultimodalInput } from './MultimodalInput';

export const TemplateSaveModal: React.FC = () => {
  const { t } = useTranslation();
  const isOpen = useSimulationStore(state => state.isSaveTemplateOpen);
  const toggle = useSimulationStore(state => state.toggleSaveTemplate);
  const saveTemplate = useSimulationStore(state => state.saveTemplate);
  const currentSim = useSimulationStore(state => state.currentSimulation);
  const agents = useSimulationStore(state => state.agents);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const addNotification = useSimulationStore(state => state.addNotification);

  if (!isOpen) return null;

  const handleSave = () => {
    if (!name) return;
    saveTemplate(name, description);
    setName('');
    setDescription('');
  };

  return (
    <div className="fixed inset-0 z-[140] flex items-center justify-center bg-slate-900/50 backdrop-blur-sm">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md overflow-hidden animate-in zoom-in-95 duration-200">
        <div className="px-6 py-4 border-b flex justify-between items-center bg-slate-50">
          <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
            <LayoutTemplate className="text-brand-600" size={20} />
            {t('components.templateSaveModal.title')}
          </h2>
          <button onClick={() => toggle(false)} className="text-slate-400 hover:text-slate-600">
            <X size={20} />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-xs text-blue-700 mb-4">
            {t('components.templateSaveModal.info', { count: agents.length })}
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
              {t('components.templateSaveModal.templateName')}
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('components.templateSaveModal.namePlaceholder')}
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-brand-500 outline-none text-sm"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
              {t('components.templateSaveModal.descriptionOptional')}
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('components.templateSaveModal.descriptionPlaceholder')}
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-brand-500 outline-none text-sm h-24 resize-none"
            />
            <div className="mt-2">
              <MultimodalInput
                helperText={t('components.templateSaveModal.imageHelper')}
                onInsert={(url) => {
                  setDescription((prev) => `${prev}${prev ? '\n' : ''}![image](${url})`);
                  addNotification('success', t('components.templateSaveModal.imageInserted'));
                }}
              />
            </div>
          </div>
        </div>

        <div className="px-6 py-4 border-t bg-slate-50 flex justify-end gap-3">
          <button onClick={() => toggle(false)} className="px-4 py-2 text-sm text-slate-600 font-medium hover:bg-slate-100 rounded-lg">
            {t('components.templateSaveModal.cancel')}
          </button>
          <button
            onClick={handleSave}
            disabled={!name}
            className="px-6 py-2 text-sm bg-brand-600 text-white font-medium hover:bg-brand-700 rounded-lg shadow-sm flex items-center gap-2 disabled:opacity-50"
          >
            <Save size={16} />
            {t('components.templateSaveModal.saveTemplate')}
          </button>
        </div>
      </div>
    </div>
  );
};
