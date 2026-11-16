/**
 * Multi-line text input field.
 *
 * For longer text content like topics, descriptions, policy text.
 *
 * Exports: TextAreaField (default)
 */

import React from 'react';

interface TextAreaFieldProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  rows?: number;
}

export default function TextAreaField({
  value,
  onChange,
  placeholder,
  disabled = false,
  rows = 4
}: TextAreaFieldProps) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      rows={rows}
      className="w-full px-3 py-2 border rounded-lg resize-y"
    />
  );
}
