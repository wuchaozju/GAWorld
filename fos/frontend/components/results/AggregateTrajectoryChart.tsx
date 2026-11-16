import React from 'react';
import type { MetricAggregatePoint, VariantAggregate } from '@/utils/resultsComputations';

const VARIANT_COLORS = [
  '#5B8AF0',
  '#E8925A',
  '#5DBF8A',
  '#B877D9',
  '#E8B84A',
  '#D96B6B',
];

interface AggregateTrajectoryChartProps {
  points?: MetricAggregatePoint[];
  variants?: VariantAggregate[];
  metric: string;
  width?: number;
  height?: number;
  meanLabel?: string;
  rangeLabel?: string;
  xLabel?: string;
  yLabel?: string;
}

const MARGIN = { left: 52, right: 24, top: 12, bottom: 44 };

function f(n: number): number { return Number(n.toFixed(2)); }
function fmt(v: number): string { return Number.isInteger(v) ? String(v) : v.toFixed(1); }

function SingleChart({
  points,
  metric,
  width,
  height,
  meanLabel,
  rangeLabel,
  color,
}: {
  points: MetricAggregatePoint[];
  metric: string;
  width: number;
  height: number;
  meanLabel: string;
  rangeLabel: string;
  color?: string;
}) {
  const plotWidth  = width  - MARGIN.left - MARGIN.right;
  const plotHeight = height - MARGIN.top  - MARGIN.bottom;
  const maxLen     = points.length;
  const yMin       = Math.min(...points.map((p) => p.min));
  const yMax       = Math.max(...points.map((p) => p.max));

  const toX = (i: number): number =>
    maxLen === 1 ? 0 : (i / (maxLen - 1)) * plotWidth;
  const toY = (v: number): number =>
    yMax === yMin ? plotHeight / 2 : plotHeight - ((v - yMin) / (yMax - yMin)) * plotHeight;

  const bandPoints = [
    ...points.map((p, i) => `${f(toX(i))},${f(toY(p.min))}`),
    ...[...points].reverse().map((p, i) => `${f(toX(maxLen - 1 - i))},${f(toY(p.max))}`),
  ].join(' ');

  const meanPts = points.map((p, i) => `${f(toX(i))},${f(toY(p.mean))}`).join(' ');
  const lineColor = color || 'var(--ss-brand-primary)';
  const bandColor = color || 'var(--ss-brand-soft)';

  return (
    <g>
      <polygon points={bandPoints}
        fill={bandColor} fillOpacity={0.5} stroke="none" />
      <polyline points={meanPts} fill="none"
        stroke={lineColor} strokeWidth={color ? 2.5 : 2} />
      {points.map((p, i) => (
        <circle key={i} cx={f(toX(i))} cy={f(toY(p.mean))} r={color ? 2 : 3}
          fill={lineColor} />
      ))}
    </g>
  );
}

export function AggregateTrajectoryChart({
  points: singlePoints,
  variants,
  metric,
  width = 600,
  height = 300,
  meanLabel = 'Mean',
  rangeLabel = 'Range',
  xLabel,
  yLabel,
}: AggregateTrajectoryChartProps): React.JSX.Element {
  const hasVariants = variants && variants.length > 0;
  const allPoints = hasVariants
    ? variants.flatMap((v) => v.points)
    : (singlePoints || []);

  if (allPoints.length === 0) return <div />;

  const plotWidth  = width  - MARGIN.left - MARGIN.right;
  const plotHeight = height - MARGIN.top  - MARGIN.bottom;
  const maxLen = hasVariants
    ? Math.max(...variants!.map((v) => v.points.length))
    : singlePoints!.length;
  const yMin = Math.min(...allPoints.map((p) => p.min));
  const yMax = Math.max(...allPoints.map((p) => p.max));

  const toX = (i: number): number =>
    maxLen === 1 ? 0 : (i / (maxLen - 1)) * plotWidth;
  const toY = (v: number): number =>
    yMax === yMin ? plotHeight / 2 : plotHeight - ((v - yMin) / (yMax - yMin)) * plotHeight;

  const labelStep = Math.max(1, Math.ceil(maxLen / 10));
  const xTicks = (hasVariants ? variants![0].points : singlePoints!)
    .map((p, i) => ({ round: p.round, x: toX(i), show: i % labelStep === 0 || i === maxLen - 1 }))
    .filter((t) => t.show);

  const yTicks = [
    { value: yMax, y: 0 },
    { value: (yMin + yMax) / 2, y: plotHeight / 2 },
    { value: yMin, y: plotHeight },
  ];

  return (
    <div>
      <div style={{ fontSize: '12px', color: 'var(--ss-workspace-muted)', marginBottom: '4px' }}>{metric}</div>
      <svg width={width} height={hasVariants ? height + 30 : height} role="img" aria-label={metric}>
        <g transform={`translate(${MARGIN.left}, ${MARGIN.top})`}>
          {yTicks.map((t, i) => (
            <g key={`y-${i}`}>
              <line x1={0} y1={t.y} x2={plotWidth} y2={t.y}
                stroke="var(--ss-workspace-border)" strokeWidth={1} />
              <text x={-8} y={t.y} textAnchor="end" dominantBaseline="middle"
                fontSize={10} fill="var(--ss-workspace-muted)">{fmt(t.value)}</text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text key={`x-${t.round}`} x={t.x} y={plotHeight + 16}
              textAnchor="middle" fontSize={10} fill="var(--ss-workspace-muted)">{t.round}</text>
          ))}
          {xLabel ? (
            <text x={plotWidth / 2} y={plotHeight + 36}
              textAnchor="middle" fontSize={11} fill="var(--ss-workspace-muted)">{xLabel}</text>
          ) : null}
          {yLabel ? (
            <text x={-plotHeight / 2} y={-38}
              textAnchor="middle" fontSize={11} fill="var(--ss-workspace-muted)"
              transform="rotate(-90)">{yLabel}</text>
          ) : null}

          {hasVariants ? (
            variants!.map((v, i) => (
              <SingleChart
                key={v.variantName}
                points={v.points}
                metric={metric}
                width={width}
                height={height}
                meanLabel={meanLabel}
                rangeLabel={rangeLabel}
                color={VARIANT_COLORS[i % VARIANT_COLORS.length]}
              />
            ))
          ) : singlePoints ? (
            <SingleChart
              points={singlePoints}
              metric={metric}
              width={width}
              height={height}
              meanLabel={meanLabel}
              rangeLabel={rangeLabel}
            />
          ) : null}
        </g>
      </svg>

      {/* Legend */}
      <ul style={{ listStyle: 'none', padding: 0, margin: '8px 0 0', fontSize: '12px' }}>
        {hasVariants ? variants!.map((v, i) => (
          <li key={v.variantName} style={{ display: 'flex', alignItems: 'center', marginBottom: '2px' }}>
            <span aria-hidden="true" style={{
              background: VARIANT_COLORS[i % VARIANT_COLORS.length],
              display: 'inline-block', width: '1rem', height: '2px', marginRight: '0.5rem',
            }} />
            {v.variantName} {meanLabel}
          </li>
        )) : (
          <li style={{ display: 'flex', alignItems: 'center', marginBottom: '2px' }}>
            <span aria-hidden="true" style={{ background: 'var(--ss-brand-primary)',
              display: 'inline-block', width: '1rem', height: '2px', marginRight: '0.5rem' }} />
            {meanLabel}
          </li>
        )}
        <li style={{ display: 'flex', alignItems: 'center', marginTop: hasVariants ? '4px' : '0' }}>
          <span aria-hidden="true" style={{ background: hasVariants ? 'var(--ss-text-muted)' : 'var(--ss-brand-soft)', opacity: 0.6,
            display: 'inline-block', width: '1rem', height: '0.75rem', marginRight: '0.5rem' }} />
          {rangeLabel}
        </li>
      </ul>
    </div>
  );
}
