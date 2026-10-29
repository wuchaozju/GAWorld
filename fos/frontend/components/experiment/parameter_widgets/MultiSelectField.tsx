/**
 * Multi-select checkboxes field.
 *
 * Exports: MultiSelectField (default)
 */

import React from 'react';

interface MultiSelectFieldProps {
  value: string[];
  onChange: (value: string[]) => void;
  options: string[];
  disabled?: boolean;
}

export default function MultiSelectField({
  value,
  onChange,
  options,
  disabled = false
}: MultiSelectFieldProps) {
  const toggleOption = (option: string) => {
    if (value.includes(option)) {
      onChange(value.filter(v => v !== option));
    } else {
      onChange([...value, option]);
    }
  };

  return (
    <div className="space-y-2">
      {options.map(option => (
        <label key={option} className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={value.includes(option)}
            onChange={() => toggleOption(option)}
            disabled={disabled}
            className="w-4 h-4 rounded"
          />
          <span>{option}</span>
        </label>
      ))}
    </div>
  );
}
