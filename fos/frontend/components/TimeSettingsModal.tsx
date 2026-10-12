
import React, { useState, useEffect } from 'react';
import { useSimulationStore } from '../store';
import { useTranslation } from 'react-i18next';
import { X, Clock } from 'lucide-react';
import { TimeUnit } from '../types';

export const TimeSettingsModal: React.FC = () => {
  const { t } = useTranslation();
  const isOpen = useSimulationStore(state => state.isTimeSettingsOpen);
  const toggle = useSimulationStore(state => state.toggleTimeSettings);
  const currentSim = useSimulationStore(state => state.currentSimulation);
  const updateTimeConfig = useSimulationStore(state => state.updateTimeConfig);

  const [step, setStep] = useState(1);
  const [unit, setUnit] = useState<TimeUnit>('hour');
  const [baseTime, setBaseTime] = useState('');

  const TIME_UNITS: {value: TimeUnit, label: string}[] = [
    { value: 'minute', label: t('components.timeSettingsModal.minute') },
    { value: 'hour', label: t('components.timeSettingsModal.hour') },
    { value: 'day', label: t('components.timeSettingsModal.day') },
    { value: 'week', label: t('components.timeSettingsModal.week') },
    { value: 'month', label: t('components.timeSettingsModal.month') },
    { value: 'year', label: t('components.timeSettingsModal.year') },
  ];

  useEffect(() => {
    if (currentSim && isOpen) {
      const tc = currentSim.timeConfig || { baseTime: new Date().toISOString(), step: 1, unit: 'hour' };
      setStep(tc.step ?? 1);
      setUnit(tc.unit ?? 'hour');
      try {
        setBaseTime(new Date(tc.baseTime).toISOString().slice(0, 16));
      } catch (e) {
        setBaseTime(new Date().toISOString().slice(0, 16));
      }
    }
  }, [currentSim, isOpen]);

  if (!isOpen || !currentSim) return null;

  const handleSave = () => {
    updateTimeConfig({
      baseTime: new Date(baseTime).toISOString(),
      step,
      unit
    });
    toggle(false);
  };

  return (
    <div className="fixed inset-0 z-[140] flex items-center justify-center bg-slate-900/50 backdrop-blur-sm">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm overflow-hidden animate-in zoom-in-95 duration-200">
        <div className="px-6 py-4 border-b flex justify-between items-center bg-slate-50">
          <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
            <Clock className="text-brand-600" size={20} />
            {t('components.timeSettingsModal.title')}
          </h2>
          <button onClick={() => toggle(false)} className="text-slate-400 hover:text-slate-600">
            <X size={20} />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <p className="text-xs text-slate-500 mb-4">
            {t('components.timeSettingsModal.description')}
          </p>

          <div>
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
              {t('components.timeSettingsModal.perRoundAdvance')}
            </label>
            <div className="flex gap-2">
              <input 
                type="number" 
                min="1"
                value={step}
                onChange={(e) => setStep(Math.max(1, parseInt(e.target.value)))}
                className="w-20 px-3 py-2 border rounded-lg focus:ring-2 focus:ring-brand-500 outline-none text-sm text-center font-bold"
              />
              <select 
                value={unit}
                onChange={(e) => setUnit(e.target.value as TimeUnit)}
                className="flex-1 px-3 py-2 border rounded-lg focus:ring-2 focus:ring-brand-500 outline-none text-sm bg-white"
              >
                {TIME_UNITS.map(u => <option key={u.value} value={u.value}>{u.label}</option>)}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
               {t('components.timeSettingsModal.calibrateStartTime')}
            </label>
            <input 
              type="datetime-local" 
              value={baseTime}
              onChange={(e) => setBaseTime(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-brand-500 outline-none text-sm text-slate-600"
            />
          </div>
        </div>

        <div className="px-6 py-4 border-t bg-slate-50 flex justify-end gap-3">
          <button onClick={() => toggle(false)} className="px-4 py-2 text-sm text-slate-600 font-medium hover:bg-slate-100 rounded-lg">
            {t('components.timeSettingsModal.cancel')}
          </button>
          <button
            onClick={handleSave}
            className="px-6 py-2 text-sm bg-brand-600 text-white font-medium hover:bg-brand-700 rounded-lg shadow-sm"
          >
            {t('components.timeSettingsModal.applySettings')}
          </button>
        </div>
      </div>
    </div>
  );
};
