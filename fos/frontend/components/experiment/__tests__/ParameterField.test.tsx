/**
 * Tests for ParameterField component.
 *
 * Tests for:
 * - Component rendering
 * - Widget routing based on ui_hint
 * - Value change callbacks
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import ParameterField, { ScenarioParam } from '../ParameterField';
import { vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: vi.fn() },
}));

describe('ParameterField', () => {
  const onChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  // =========================================================================
  // Widget Routing Tests
  // =========================================================================

  describe('Widget Routing', () => {
    test('should render SliderField for ui_hint="slider"', () => {
      const param: ScenarioParam = {
        type: 'integer',
        default: 50,
        ui_hint: 'slider',
        min: 0,
        max: 100,
        step: 1,
      };

      const { container } = render(
        <ParameterField param={param} value={50} onChange={onChange} />
      );

      const slider = container.querySelector('input[type="range"]');
      const numberInput = container.querySelector('input[type="number"]');
      expect(slider).toBeInTheDocument();
      expect(numberInput).toBeInTheDocument();
    });

    test('should render PercentageField for ui_hint="percentage"', () => {
      const param: ScenarioParam = {
        type: 'integer',
        default: 0.5,
        ui_hint: 'percentage',
      };

      const { container } = render(
        <ParameterField param={param} value={0.5} onChange={onChange} />
      );

      const slider = container.querySelector('input[type="range"]');
      expect(slider).toBeInTheDocument();
      expect(screen.getByText('50%')).toBeInTheDocument();
    });

    test('should render TextAreaField for ui_hint="textarea"', () => {
      const param: ScenarioParam = {
        type: 'string',
        default: '',
        ui_hint: 'textarea',
        placeholder: 'Enter text',
      };

      const { container } = render(
        <ParameterField param={param} value="" onChange={onChange} />
      );

      const textarea = container.querySelector('textarea');
      expect(textarea).toBeInTheDocument();
      expect(textarea).toHaveAttribute('placeholder', 'Enter text');
    });

    test('should render ToggleField for ui_hint="toggle"', () => {
      const param: ScenarioParam = {
        type: 'boolean',
        default: false,
        ui_hint: 'toggle',
      };

      const { container } = render(
        <ParameterField param={param} value={false} onChange={onChange} />
      );

      const checkbox = container.querySelector('input[type="checkbox"]');
      expect(checkbox).toBeInTheDocument();
      expect(screen.getByText('Disabled')).toBeInTheDocument();
    });
  });

  // =========================================================================
  // Value Change Tests
  // =========================================================================

  describe('Value Changes', () => {
    test('should call onChange when slider value changes', () => {
      const param: ScenarioParam = {
        type: 'integer',
        default: 50,
        ui_hint: 'slider',
        min: 0,
        max: 100,
        step: 1,
      };

      const { container } = render(
        <ParameterField param={param} value={50} onChange={onChange} />
      );

      const numberInput = container.querySelector('input[type="number"]') as HTMLInputElement;
      expect(numberInput).toBeInTheDocument();

      fireEvent.change(numberInput, { target: { value: '75' } });

      expect(onChange).toHaveBeenCalledWith(75);
    });

    test('should call onChange when toggle is clicked', () => {
      const param: ScenarioParam = {
        type: 'boolean',
        default: false,
        ui_hint: 'toggle',
      };

      const { container } = render(
        <ParameterField param={param} value={false} onChange={onChange} />
      );

      const label = container.querySelector('label') as HTMLLabelElement;
      fireEvent.click(label);

      expect(onChange).toHaveBeenCalledWith(true);
    });
  });
});
