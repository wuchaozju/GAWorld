/*
This file builds a markdown report from result data that was already computed.
generateMarkdownReport checks the input, writes the title and summary, and adds one final-values table for each metric.
buildMetricSection makes the markdown block for one metric.
buildTableRows makes the table rows for one metric and stops if an agent has no values.
getLastValue picks the final number from one agent's value list and stops if the list is empty.
*/

import type { Series } from './resultsComputations';

export type ReportLabels = {
  summary: string;
  noSummary: string;
  finalValues: string;
  agent: string;
  finalValue: string;
};

export type ReportInput = {
  title: string;
  metrics: { name: string; series: Series[] }[];
  summary: string | null;
};

export function generateMarkdownReport(input: ReportInput, labels: ReportLabels): string {
  if (typeof input.title !== 'string' || input.title.length === 0) {
    throw new Error('generateMarkdownReport: title must be a non-empty string');
  }

  if (!Array.isArray(input.metrics)) {
    throw new Error('generateMarkdownReport: metrics must be an array');
  }

  const sections = [
    `# ${input.title}`,
    `## ${labels.summary}`,
    input.summary === null ? labels.noSummary : input.summary,
  ];

  if (input.metrics.length === 0) {
    return sections.join('\n\n');
  }

  sections.push(`## ${labels.finalValues}`);

  for (const metric of input.metrics) {
    sections.push(buildMetricSection(metric.name, metric.series, labels));
  }

  return sections.join('\n\n');
}

function buildMetricSection(metricName: string, seriesList: Series[], labels: ReportLabels): string {
  const tableLines = [
    `| ${labels.agent} | ${labels.finalValue} |`,
    '| --- | --- |',
    ...buildTableRows(metricName, seriesList),
  ];

  return `### ${metricName}\n\n${tableLines.join('\n')}`;
}

function buildTableRows(metricName: string, seriesList: Series[]): string[] {
  const rows: string[] = [];

  for (const series of seriesList) {
    const lastValue = getLastValue(metricName, series);
    rows.push(`| ${series.agentName} | ${String(lastValue)} |`);
  }

  return rows;
}

function getLastValue(metricName: string, series: Series): number {
  if (series.values.length === 0) {
    throw new Error(
      `generateMarkdownReport: series for agent "${series.agentName}" in metric "${metricName}" has no values`,
    );
  }

  return series.values[series.values.length - 1];
}
