/**
 * Percentage slider field for 0-100% parameters.
 *
 * Renders a slider with percentage display.
 * Stores values as 0-1 float, displays as 0-100%.
 *
 * Exports: PercentageField (default)
 */

import React from 'react';
import { useTranslation } from 'react-i18next';

interface PercentageFieldProps {
  value: number; // 0-1 float
  onChange: (value: number) => void;
  disabled?: boolean;
}

export default function PercentageField({
  value,
  onChange,
  disabled = false
}: PercentageFieldProps) {
  const { t } = useTranslation();
  const percentValue = Math.round(value * 100);

  return (
    <div className="flex items-center gap-4">
      <input
        type="range"
        min={0}
        max={100}
        value={percentValue}
        onChange={(e) => onChange(parseInt(e.target.value) / 100)}
        disabled={disabled}
        className="flex-1"
      />
      <span className="w-16 text-right">{percentValue}%</span>
    </div>
  );
}
