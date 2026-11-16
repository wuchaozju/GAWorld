/**
 * Parameter field router component.
 *
 * Routes to appropriate widget based on ui_hint metadata.
 * Acts as a thin dispatcher for type-specific parameter inputs.
 *
 * Exports: ParameterField (default)
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import * as Widgets from './parameter_widgets';

export interface ScenarioParam {
  type: 'integer' | 'string' | 'boolean' | 'array';
  default: any;
  ui_hint: string;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
  placeholder?: string;
}

interface ParameterFieldProps {
  param: ScenarioParam;
  value: any;
  onChange: (value: any) => void;
  disabled?: boolean;
}

export default function ParameterField({
  param,
  value,
  onChange,
  disabled = false
}: ParameterFieldProps) {
  const { t } = useTranslation();

  const commonProps = { value, onChange, disabled };

  switch (param.ui_hint) {
    case 'slider':
      return (
        <Widgets.SliderField
          {...commonProps}
          min={param.min ?? 0}
          max={param.max ?? 100}
          step={param.step ?? 1}
        />
      );

    case 'number':
      return (
        <Widgets.NumberField
          {...commonProps}
          min={param.min ?? 0}
          max={param.max ?? 100}
          step={param.step ?? 1}
        />
      );

    case 'percentage':
      return <Widgets.PercentageField {...commonProps} />;

    case 'textarea':
      return (
        <Widgets.TextAreaField
          {...commonProps}
          placeholder={param.placeholder}
          rows={4}
        />
      );

    case 'text':
      return (
        <Widgets.TextField
          {...commonProps}
          placeholder={param.placeholder}
        />
      );

    case 'select':
      return (
        <Widgets.SelectField
          {...commonProps}
          options={param.options ?? []}
        />
      );

    case 'toggle':
      return <Widgets.ToggleField {...commonProps} />;

    case 'list':
      return <Widgets.ListField {...commonProps} />;

    case 'multiselect':
      return (
        <Widgets.MultiSelectField
          {...commonProps}
          options={param.options ?? []}
        />
      );

    case 'key_value':
      return <Widgets.KeyValueField {...commonProps} />;

    case 'drag_list':
      return <Widgets.DragListField {...commonProps} />;

    default:
      // Fallback to text input for unknown ui_hint
      return (
        <Widgets.TextField
          {...commonProps}
          placeholder={param.placeholder ?? t('param.uiHint.text')}
        />
      );
  }
}
