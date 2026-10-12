import { describe, it, expect } from 'vitest';
import { metricChartGeometry, metricChartBounds } from './metricChartGeometry';
import type { Series } from './resultsComputations';

describe('metricChartGeometry', () => {
  it('maps each agent series to polyline points across full width and inverted height', () => {
    const series: Series[] = [
      { agentId: 'a', agentName: 'Alice', values: [0, 10] },
      { agentId: 'b', agentName: 'Bob', values: [5, 5] },
    ];
    expect(metricChartGeometry(series, 100, 100)).toEqual([
      { agentId: 'a', agentName: 'Alice', points: '0,100 100,0' },
      { agentId: 'b', agentName: 'Bob', points: '0,50 100,50' },
    ]);
  });

  it('places a single-round series at x=0', () => {
    const series: Series[] = [
      { agentId: 'a', agentName: 'Alice', values: [7] },
      { agentId: 'b', agentName: 'Bob', values: [3] },
    ];
    expect(metricChartGeometry(series, 100, 100)).toEqual([
      { agentId: 'a', agentName: 'Alice', points: '0,0' },
      { agentId: 'b', agentName: 'Bob', points: '0,100' },
    ]);
  });

  it('centers vertically when all values are equal', () => {
    const series: Series[] = [
      { agentId: 'a', agentName: 'Alice', values: [5, 5] },
    ];
    expect(metricChartGeometry(series, 100, 100)).toEqual([
      { agentId: 'a', agentName: 'Alice', points: '0,50 100,50' },
    ]);
  });

  it('throws when series is empty', () => {
    expect(() => metricChartGeometry([], 100, 100)).toThrow();
  });

  it('throws when a series has no values', () => {
    expect(() => metricChartGeometry(
      [{ agentId: 'a', agentName: 'Alice', values: [] }], 100, 100,
    )).toThrow();
  });

  it('throws when width or height is not positive', () => {
    const series: Series[] = [{ agentId: 'a', agentName: 'Alice', values: [1, 2] }];
    expect(() => metricChartGeometry(series, 0, 100)).toThrow();
    expect(() => metricChartGeometry(series, 100, -1)).toThrow();
  });
});

describe('metricChartBounds', () => {
  it('returns yMin, yMax, and maxLen across all series', () => {
    const series: Series[] = [
      { agentId: 'a', agentName: 'Alice', values: [5, 10, 8] },
      { agentId: 'b', agentName: 'Bob', values: [3, 12] },
    ];
    expect(metricChartBounds(series)).toEqual({ yMin: 3, yMax: 12, maxLen: 3 });
  });

  it('throws on an empty series array', () => {
    expect(() => metricChartBounds([])).toThrow();
  });
});
