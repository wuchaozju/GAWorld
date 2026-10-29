/**
 * Slider input field for numeric parameters.
 *
 * Renders a range slider with number input for precise control.
 * Handles min/max bounds and step increments.
 *
 * Exports: SliderField (default)
 */

import React from 'react';
import { useTranslation } from 'react-i18next';

interface SliderFieldProps {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
}

export default function SliderField({
  value,
  onChange,
  min = 0,
  max = 100,
  step = 1,
  disabled = false
}: SliderFieldProps) {
  const { t } = useTranslation();

  return (
    <div className="flex items-center gap-4">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        disabled={disabled}
        className="flex-1"
      />
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || min)}
        disabled={disabled}
        className="w-20 px-2 py-1 border rounded"
      />
    </div>
  );
}
