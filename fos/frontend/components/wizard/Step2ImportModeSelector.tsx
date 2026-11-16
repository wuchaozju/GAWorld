/**
 * Step2ImportModeSelector component for SimulationWizard.
 *
 * Mode selector buttons for choosing agent import method.
 *
 * Props:
 *   - importMode: Current import mode ('default' | 'generate' | 'custom')
 *   - onModeChange: Callback when mode is changed
 *   - defaultText: Text for default mode button
 *   - generateText: Text for generate mode button
 *   - customText: Text for custom/import mode button
 */

import React from 'react';
import { Sparkles } from 'lucide-react';

type ImportMode = 'default' | 'generate' | 'custom';

interface Step2ImportModeSelectorProps {
  importMode: ImportMode;
  onModeChange: (mode: ImportMode) => void;
  defaultText: string;
  generateText: string;
  customText: string;
}

export const Step2ImportModeSelector: React.FC<Step2ImportModeSelectorProps> = ({
  importMode,
  onModeChange,
  defaultText,
  generateText,
  customText,
}) => {
  return (
    <div className="flex justify-center mb-4">
      <div className="bg-slate-100 p-1 rounded-lg inline-flex">
        {/* AI Generate - Now first and recommended */}
        <button
          onClick={() => onModeChange('generate')}
          className={`px-4 py-2 text-sm font-medium rounded-md transition-all flex items-center gap-2 ${
            importMode === 'generate'
              ? 'bg-white shadow text-purple-600'
              : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          <Sparkles size={14} />
          {generateText}
        </button>
        {/* File Import - Middle option */}
        <button
          onClick={() => onModeChange('custom')}
          className={`px-4 py-2 text-sm font-medium rounded-md transition-all ${
            importMode === 'custom'
              ? 'bg-white shadow text-brand-600'
              : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          {customText}
        </button>
        {/* Template Agents - Now last (rarely used) */}
        <button
          onClick={() => onModeChange('default')}
          className={`px-4 py-2 text-sm font-medium rounded-md transition-all ${
            importMode === 'default'
              ? 'bg-white shadow text-brand-600'
              : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          {defaultText}
        </button>
      </div>
    </div>
  );
};
