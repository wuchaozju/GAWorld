/**
 * Single-line text input field.
 *
 * For short string parameters.
 *
 * Exports: TextField (default)
 */

import React from 'react';

interface TextFieldProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
}

export default function TextField({
  value,
  onChange,
  placeholder,
  disabled = false
}: TextFieldProps) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      className="w-full px-3 py-2 border rounded-lg"
    />
  );
}
