/*
This file turns metric number lists into SVG line points.
metricChartGeometry checks the inputs, finds the full chart range, and builds the point string for each agent.
*/

import type { Series } from './resultsComputations';

export type AgentPolyline = { agentId: string; agentName: string; points: string };

function validateSeries(series: Series[]): void {
  if (!Array.isArray(series) || series.length === 0) {
    throw new Error('metricChartGeometry: series must be a non-empty array');
  }

  for (const item of series) {
    if (item.values.length === 0) {
      throw new Error(`metricChartGeometry: series for agent "${item.agentName}" has no values`);
    }
  }
}

function validateDimensions(width: number, height: number): void {
  if (width <= 0 || height <= 0) {
    throw new Error('metricChartGeometry: width and height must be positive numbers');
  }
}

function getValueBounds(series: Series[]): { yMin: number; yMax: number; maxLen: number } {
  let yMin = series[0].values[0];
  let yMax = series[0].values[0];
  let maxLen = series[0].values.length;

  for (const item of series) {
    if (item.values.length > maxLen) {
      maxLen = item.values.length;
    }

    for (const value of item.values) {
      if (value < yMin) {
        yMin = value;
      }
      if (value > yMax) {
        yMax = value;
      }
    }
  }

  return { yMin, yMax, maxLen };
}

function roundCoordinate(value: number): number {
  return Number(value.toFixed(2));
}

function buildPoints(
  values: number[],
  width: number,
  height: number,
  maxLen: number,
  yMin: number,
  yMax: number,
): string {
  return values
    .map((value, index) => {
      const x = maxLen === 1 ? 0 : (index / (maxLen - 1)) * width;
      const y = yMax === yMin ? height / 2 : height - ((value - yMin) / (yMax - yMin)) * height;
      return `${roundCoordinate(x)},${roundCoordinate(y)}`;
    })
    .join(' ');
}

export function metricChartBounds(
  series: Series[],
): { yMin: number; yMax: number; maxLen: number } {
  validateSeries(series);
  return getValueBounds(series);
}

export function metricChartGeometry(
  series: Series[],
  width: number,
  height: number,
): AgentPolyline[] {
  validateSeries(series);
  validateDimensions(width, height);

  const { yMin, yMax, maxLen } = getValueBounds(series);

  return series.map((item) => ({
    agentId: item.agentId,
    agentName: item.agentName,
    points: buildPoints(item.values, width, height, maxLen, yMin, yMax),
  }));
}
