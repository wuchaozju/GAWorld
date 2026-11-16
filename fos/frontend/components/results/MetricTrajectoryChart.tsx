/*
This file draws a metric chart that is easier to read.
formatTick turns chart numbers into short labels, parseCoords turns SVG point text back into x and y pairs, and MetricTrajectoryChart shows axes, guide lines, point dots, and a color key for each agent.
*/

import React from 'react';
import { metricChartGeometry, metricChartBounds } from '@/utils/metricChartGeometry';
import type { Series } from '@/utils/resultsComputations';

interface MetricTrajectoryChartProps {
  series: Series[];
  metric: string;
  width?: number;
  height?: number;
}

const COLORS = [
  '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
];

const MARGIN = { left: 48, right: 12, top: 12, bottom: 28 };

function formatTick(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

function parseCoords(points: string): { x: number; y: number }[] {
  return points
    .split(' ')
    .filter((p) => p.length > 0)
    .map((pair) => {
      const parts = pair.split(',');
      return { x: Number(parts[0]), y: Number(parts[1]) };
    });
}

export function MetricTrajectoryChart({
  series,
  metric,
  width = 600,
  height = 300,
}: MetricTrajectoryChartProps): React.JSX.Element {
  const plotWidth = width - MARGIN.left - MARGIN.right;
  const plotHeight = height - MARGIN.top - MARGIN.bottom;
  const lines = metricChartGeometry(series, plotWidth, plotHeight);
  const { yMin, yMax, maxLen } = metricChartBounds(series);

  const yTicks = [
    { value: yMax, y: 0 },
    { value: (yMin + yMax) / 2, y: plotHeight / 2 },
    { value: yMin, y: plotHeight },
  ];

  const labelStep = Math.max(1, Math.ceil(maxLen / 10));
  const xTicks = Array.from({ length: maxLen }, (_, i) => ({
    round: i + 1,
    x: maxLen === 1 ? 0 : (i / (maxLen - 1)) * plotWidth,
    show: i % labelStep === 0 || i === maxLen - 1,
  })).filter((t) => t.show);

  return (
    <div>
      <div style={{ fontSize: '12px', color: 'var(--ss-workspace-muted)', marginBottom: '4px' }}>{metric}</div>
      <svg width={width} height={height} role="img" aria-label={metric}>
        <g transform={`translate(${MARGIN.left}, ${MARGIN.top})`}>
          {yTicks.map((t, i) => (
            <g key={`y-${i}`}>
              <line x1={0} y1={t.y} x2={plotWidth} y2={t.y} stroke="var(--ss-workspace-border)" strokeWidth={1} />
              <text x={-8} y={t.y} textAnchor="end" dominantBaseline="middle" fontSize={10} fill="var(--ss-workspace-muted)">
                {formatTick(t.value)}
              </text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text key={`x-${t.round}`} x={t.x} y={plotHeight + 16} textAnchor="middle" fontSize={10} fill="var(--ss-workspace-muted)">
              {t.round}
            </text>
          ))}
          {lines.map((line, index) => {
            const color = COLORS[index % COLORS.length];
            const coords = parseCoords(line.points);
            return (
              <g key={line.agentId}>
                <polyline data-agent={line.agentId} points={line.points} fill="none" stroke={color} strokeWidth={2} />
                {coords.map((c, ci) => (
                  <circle key={ci} cx={c.x} cy={c.y} r={2.5} fill={color} />
                ))}
              </g>
            );
          })}
        </g>
      </svg>
      <ul style={{ listStyle: 'none', padding: 0, margin: '8px 0 0', fontSize: '12px' }}>
        {lines.map((line, index) => (
          <li key={line.agentId} style={{ display: 'flex', alignItems: 'center', marginBottom: '2px' }}>
            <span
              aria-hidden="true"
              style={{
                backgroundColor: COLORS[index % COLORS.length],
                display: 'inline-block', width: '0.75rem', height: '0.75rem', marginRight: '0.5rem',
              }}
            />
            {line.agentName}
          </li>
        ))}
      </ul>
    </div>
  );
}
