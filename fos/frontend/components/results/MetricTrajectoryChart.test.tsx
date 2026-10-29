import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MetricTrajectoryChart } from './MetricTrajectoryChart';
import { metricChartGeometry } from '@/utils/metricChartGeometry';
import type { Series } from '@/utils/resultsComputations';

const series: Series[] = [
  { agentId: 'a', agentName: 'Alice', values: [0, 10] },
  { agentId: 'b', agentName: 'Bob', values: [5, 5] },
];

describe('MetricTrajectoryChart', () => {
  it('renders the metric name and a legend entry per agent', () => {
    render(<MetricTrajectoryChart series={series} metric="score" width={100} height={100} />);
    expect(screen.getByText('score')).toBeTruthy();
    expect(screen.getByText('Alice')).toBeTruthy();
    expect(screen.getByText('Bob')).toBeTruthy();
  });

  it('draws one polyline per agent using the real geometry points', () => {
    const { container } = render(
      <MetricTrajectoryChart series={series} metric="score" width={100} height={100} />,
    );
    const polylines = container.querySelectorAll('polyline');
    expect(polylines).toHaveLength(2);

    const expected = metricChartGeometry(series, 40, 60);
    expect(container.querySelector('polyline[data-agent="a"]')?.getAttribute('points'))
      .toBe(expected[0].points);
    expect(container.querySelector('polyline[data-agent="b"]')?.getAttribute('points'))
      .toBe(expected[1].points);
  });

  it('throws when given no series', () => {
    expect(() => render(<MetricTrajectoryChart series={[]} metric="score" />)).toThrow();
  });
});
