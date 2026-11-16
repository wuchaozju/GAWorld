/**
 * Toggle switch for boolean parameters.
 *
 * Exports: ToggleField (default)
 */

import React from 'react';

interface ToggleFieldProps {
  value: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}

export default function ToggleField({
  value,
  onChange,
  disabled = false
}: ToggleFieldProps) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
        className="w-5 h-5 rounded"
      />
      <span className="text-sm">{value ? 'Enabled' : 'Disabled'}</span>
    </label>
  );
}
