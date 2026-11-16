/**
 * Step1BasicInfo component for SimulationWizard.
 *
 * Basic information input for experiment name.
 *
 * Props:
 *   - name: Current experiment name value
 *   - onNameChange: Callback when name is changed
 *   - placeholder: Placeholder text for name input
 *   - labelText: Label for the input field
 */

import React from 'react';

interface Step1BasicInfoProps {
  name: string;
  onNameChange: (value: string) => void;
  placeholder: string;
  labelText: string;
}

export const Step1BasicInfo: React.FC<Step1BasicInfoProps> = ({
  name,
  onNameChange,
  placeholder,
  labelText,
}) => {
  return (
    <div>
      <label className="block text-sm font-semibold text-slate-700 mb-2">
        {labelText}
      </label>
      <input
        type="text"
        value={name}
        onChange={(e) => onNameChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-brand-500 outline-none text-sm"
      />
    </div>
  );
};
