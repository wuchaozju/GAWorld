/**
 * Step1TimeConfiguration component for SimulationWizard.
 *
 * Time settings configuration for simulation time flow.
 *
 * Props:
 *   - baseTime: Base world time as ISO string
 *   - timeUnit: Time unit (minute, hour, day, week, month, year)
 *   - timeStep: Number of time units to advance per turn
 *   - onBaseTimeChange: Callback when base time is changed
 *   - onTimeUnitChange: Callback when time unit is changed
 *   - onTimeStepChange: Callback when time step is changed
 */

import React from 'react';
import { Clock } from 'lucide-react';
import { TimeUnit } from '../../types';

interface Step1TimeConfigurationProps {
  baseTime: string;
  timeUnit: TimeUnit;
  timeStep: number;
  onBaseTimeChange: (value: string) => void;
  onTimeUnitChange: (value: TimeUnit) => void;
  onTimeStepChange: (value: number) => void;
  t: (key: string) => string;
}

const TIME_UNITS = (t: (key: string) => string): { value: TimeUnit; label: string }[] => [
  { value: 'minute', label: t('wizard.timeUnits.minute') },
  { value: 'hour', label: t('wizard.timeUnits.hour') },
  { value: 'day', label: t('wizard.timeUnits.day') },
  { value: 'week', label: t('wizard.timeUnits.week') },
  { value: 'month', label: t('wizard.timeUnits.month') },
  { value: 'year', label: t('wizard.timeUnits.year') }
];

export const Step1TimeConfiguration: React.FC<Step1TimeConfigurationProps> = ({
  baseTime,
  timeUnit,
  timeStep,
  onBaseTimeChange,
  onTimeUnitChange,
  onTimeStepChange,
  t,
}) => {
  return (
    <div className="bg-indigo-50 border border-indigo-100 rounded-lg p-5">
      <label className="block text-sm font-bold text-indigo-900 mb-3 flex items-center gap-2">
        <Clock size={16} />
        {t('wizard.step1.timeSettings')}
      </label>
      <div className="flex items-end gap-4 flex-wrap">
        <div className="flex-1 min-w-[180px]">
          <span className="text-xs text-indigo-700 mb-1 block font-medium">
            {t('wizard.step1.baseWorldTime')}
          </span>
          <div className="relative">
            <input
              type="datetime-local"
              value={baseTime}
              onChange={(e) => onBaseTimeChange(e.target.value)}
              className="w-full px-3 py-2 border border-indigo-200 rounded text-sm focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>
        </div>
        <div className="flex items-center gap-2 bg-white px-3 py-2 border border-indigo-200 rounded">
          <span className="text-xs text-indigo-700 whitespace-nowrap">
            {t('wizard.step1.advancePerTurn')}
          </span>
          <input
            type="number"
            min="1"
            value={timeStep}
            onChange={(e) => onTimeStepChange(Math.max(1, parseInt(e.target.value)))}
            className="w-14 text-center border-b border-indigo-300 focus:border-indigo-600 outline-none text-sm font-bold"
          />
          <select
            value={timeUnit}
            onChange={(e) => onTimeUnitChange(e.target.value as TimeUnit)}
            className="text-sm bg-transparent border-none outline-none font-bold text-slate-700 cursor-pointer"
          >
            {TIME_UNITS(t).map((u) => (
              <option key={u.value} value={u.value}>
                {u.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <p className="text-[10px] text-indigo-600 mt-2">
        {t('wizard.step1.currentSettingsPreview')}
        {(() => {
          const d = new Date(baseTime);
          const msMap: any = {
            minute: 60000,
            hour: 3600000,
            day: 86400000,
            week: 604800000
          };
          if (msMap[timeUnit]) {
            d.setTime(
              d.getTime() + msMap[timeUnit] * timeStep * 10
            );
            return d.toLocaleString();
          }
          return t('wizard.step1.dynamicCalculation');
        })()}
      </p>
    </div>
  );
};
