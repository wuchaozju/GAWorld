import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { AggregateTrajectoryChart } from './AggregateTrajectoryChart';
import type { MetricAggregatePoint } from '@/utils/resultsComputations';

const points: MetricAggregatePoint[] = [
  { round: 1, mean: 15, min: 10, max: 20 },
  { round: 2, mean: 30, min: 25, max: 35 },
];

describe('AggregateTrajectoryChart', () => {
  it('renders a band polygon and a mean polyline', () => {
    const { container } = render(<AggregateTrajectoryChart points={points} metric="payoff" />);
    expect(container.querySelector('polygon')).toBeTruthy();
    expect(container.querySelector('polyline')).toBeTruthy();
  });
  it('shows the metric name', () => {
    render(<AggregateTrajectoryChart points={points} metric="payoff" />);
    expect(screen.getByText('payoff')).toBeTruthy();
  });
  it('labels each round on the X-axis', () => {
    render(<AggregateTrajectoryChart points={points} metric="payoff" />);
    expect(screen.getByText('1')).toBeTruthy();
    expect(screen.getByText('2')).toBeTruthy();
  });
  it('shows Mean and Range in the legend', () => {
    render(<AggregateTrajectoryChart points={points} metric="payoff" />);
    expect(screen.getByText('Mean')).toBeTruthy();
    expect(screen.getByText('Range')).toBeTruthy();
  });
});
