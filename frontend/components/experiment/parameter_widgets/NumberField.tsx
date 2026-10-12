/**
 * Number input field with stepper buttons.
 *
 * Renders a number input with +/- buttons for increment/decrement.
 * Handles min/max bounds and step increments.
 *
 * Exports: NumberField (default)
 */

import React from 'react';
import { useTranslation } from "react-i18next";
import { Minus, Plus } from 'lucide-react';

interface NumberFieldProps {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
}

export default function NumberField({
  value,
  onChange,
  min = 0,
  max = 100,
  step = 1,
  disabled = false
}: NumberFieldProps) {
  const { t } = useTranslation();
  const handleDecrement = () => {
    const newValue = Math.max(min, value - step);
    onChange(newValue);
  };

  const handleIncrement = () => {
    const newValue = Math.min(max, value + step);
    onChange(newValue);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const parsed = parseFloat(e.target.value);
    if (!isNaN(parsed)) {
      const clamped = Math.min(max, Math.max(min, parsed));
      onChange(clamped);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={handleDecrement}
        disabled={disabled || value <= min}
        className="p-2 rounded-md border disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
        aria-label={t("common.decrease")}
      >
        <Minus className="w-4 h-4" />
      </button>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={handleInputChange}
        disabled={disabled}
        className="w-20 px-3 py-2 border rounded-md text-center focus:outline-none focus:ring-2 disabled:opacity-60 disabled:cursor-not-allowed"
        style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)', color: 'var(--ss-heading)' }}
      />
      <button
        type="button"
        onClick={handleIncrement}
        disabled={disabled || value >= max}
        className="p-2 rounded-md border disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
        aria-label={t("common.increase")}
      >
        <Plus className="w-4 h-4" />
      </button>
    </div>
  );
}
