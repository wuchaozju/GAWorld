/*
This file shows a simple horizontal bar chart from bar data that is already ready to display.
CountBarChart checks that it got a non-empty list, turns each value into a width percentage, and renders each bar row in the same order it was given.
*/
import React from 'react';

interface CountBarChartBar {
  label: string;
  value: number;
}

interface CountBarChartProps {
  bars: CountBarChartBar[];
}

export function CountBarChart({ bars }: CountBarChartProps) {
  if (!Array.isArray(bars) || bars.length === 0) {
    throw new Error('CountBarChart: bars must be a non-empty array');
  }

  const max = Math.max(...bars.map((bar) => bar.value));

  return (
    <ul>
      {bars.map((bar) => {
        const pct = max === 0 ? 0 : Number(((bar.value / max) * 100).toFixed(2));

        return (
          <li key={`${bar.label}-${bar.value}`}>
            <span>{bar.label}</span>
            <div
              data-label={bar.label}
              data-pct={pct}
              style={{ width: `${pct}%`, backgroundColor: '#4a7a6a', height: '12px' }}
            />
            <span>{bar.value}</span>
          </li>
        );
      })}
    </ul>
  );
}
