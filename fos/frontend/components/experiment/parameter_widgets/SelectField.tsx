/**
 * Dropdown select field for enum options.
 *
 * Exports: SelectField (default)
 */

import React from 'react';

interface SelectFieldProps {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  disabled?: boolean;
}

export default function SelectField({
  value,
  onChange,
  options,
  disabled = false
}: SelectFieldProps) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className="w-full px-3 py-2 border rounded-lg"
    >
      {options.map(option => (
        <option key={option} value={option}>
          {option}
        </option>
      ))}
    </select>
  );
}
