/**
 * WizardHeader component for SimulationWizard.
 *
 * Displays the wizard title, step indicators, and close button.
 *
 * Props:
 *   - step: Current wizard step (1, 2, or 3)
 *   - title: Title text for the wizard
 *   - onClose: Callback when close button is clicked
 */

import React from 'react';
import { X } from 'lucide-react';

interface WizardHeaderProps {
  step: number;
  title: string;
  onClose: () => void;
}

export const WizardHeader: React.FC<WizardHeaderProps> = ({ step, title, onClose }) => {
  return (
    <div className="px-6 py-4 border-b flex justify-between items-center bg-slate-50 shrink-0">
      <div>
        <h2 className="text-lg font-bold text-slate-800">{title}</h2>
        <div className="flex gap-2 mt-1">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className={`h-1.5 w-8 rounded-full ${
                step >= i ? 'bg-brand-500' : 'bg-slate-200'
              }`}
            />
          ))}
        </div>
      </div>
      <button
        onClick={onClose}
        className="text-slate-400 hover:text-slate-600"
      >
        <X size={20} />
      </button>
    </div>
  );
};
