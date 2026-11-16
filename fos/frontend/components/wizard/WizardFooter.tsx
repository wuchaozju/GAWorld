/**
 * WizardFooter component for SimulationWizard.
 *
 * Displays navigation buttons for the wizard (Cancel, Previous, Next, Start).
 *
 * Props:
 *   - step: Current wizard step (1, 2, or 3)
 *   - onCancel: Callback when cancel button is clicked
 *   - onNext: Callback when next button is clicked
 *   - onPrevious: Callback when previous button is clicked
 *   - onFinish: Callback when finish/start button is clicked
 *   - isSaving: Whether simulation is being saved
 *   - cancelText: Text for cancel button
 *   - previousText: Text for previous button
 *   - nextText: Text for next button
 *   - finishText: Text for finish button
 *   - savingText: Text for saving state
 */

import React from 'react';
import { Loader2 } from 'lucide-react';

interface WizardFooterProps {
  step: number;
  onCancel: () => void;
  onNext: () => void;
  onPrevious: () => void;
  onFinish: () => void;
  isSaving: boolean;
  cancelText: string;
  previousText: string;
  nextText: string;
  finishText: string;
  savingText: string;
}

export const WizardFooter: React.FC<WizardFooterProps> = ({
  step,
  onCancel,
  onNext,
  onPrevious,
  onFinish,
  isSaving,
  cancelText,
  previousText,
  nextText,
  finishText,
  savingText,
}) => {
  return (
    <div className="px-6 py-4 border-t bg-slate-50 flex justify-end gap-3 shrink-0">
      {step > 1 && (
        <button
          onClick={onPrevious}
          className="px-4 py-2 text-sm text-slate-600 font-medium hover:bg-slate-100 rounded-lg"
        >
          {previousText}
        </button>
      )}
      {step === 1 && (
        <button
          onClick={onCancel}
          className="px-4 py-2 text-sm text-slate-600 font-medium hover:bg-slate-100 rounded-lg"
        >
          {cancelText}
        </button>
      )}
      {step < 3 && (
        <button
          onClick={onNext}
          className="px-6 py-2 text-sm bg-brand-600 text-white font-medium hover:bg-brand-700 rounded-lg shadow-sm"
        >
          {nextText}
        </button>
      )}
      {step === 3 && (
        <button
          onClick={onFinish}
          className="px-6 py-2 text-sm bg-green-600 text-white font-medium hover:bg-green-700 rounded-lg shadow-sm"
          disabled={isSaving}
        >
          {isSaving ? (
            <span className="flex items-center gap-2">
              <Loader2 size={16} className="animate-spin" />
              {savingText}
            </span>
          ) : (
            finishText
          )}
        </button>
      )}
    </div>
  );
};
