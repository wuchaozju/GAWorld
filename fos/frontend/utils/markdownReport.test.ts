import { describe, it, expect } from 'vitest';
import { generateMarkdownReport } from './markdownReport';
import type { ReportInput, ReportLabels } from './markdownReport';

const labels: ReportLabels = {
  summary: 'Summary',
  noSummary: 'Not generated yet.',
  finalValues: 'Final values',
  agent: 'Agent',
  finalValue: 'Final value',
};

const baseInput: ReportInput = {
  title: 'Public goods game',
  metrics: [
    { name: 'score', series: [
      { agentId: 'a', agentName: 'Alice', values: [10, 12, 15] },
      { agentId: 'b', agentName: 'Bob', values: [8, 9, 9] },
    ] },
  ],
  summary: 'Agents cooperated.',
};

describe('generateMarkdownReport', () => {
  it('renders title, summary, and a final-values table per metric', () => {
    expect(generateMarkdownReport(baseInput, labels)).toBe(
      '# Public goods game\n\n' +
      '## Summary\n\n' +
      'Agents cooperated.\n\n' +
      '## Final values\n\n' +
      '### score\n\n' +
      '| Agent | Final value |\n' +
      '| --- | --- |\n' +
      '| Alice | 15 |\n' +
      '| Bob | 9 |'
    );
  });

  it('uses the noSummary label when summary is null', () => {
    expect(generateMarkdownReport({ ...baseInput, summary: null }, labels)).toBe(
      '# Public goods game\n\n' +
      '## Summary\n\n' +
      'Not generated yet.\n\n' +
      '## Final values\n\n' +
      '### score\n\n' +
      '| Agent | Final value |\n' +
      '| --- | --- |\n' +
      '| Alice | 15 |\n' +
      '| Bob | 9 |'
    );
  });

  it('omits the final-values section when there are no metrics', () => {
    expect(generateMarkdownReport({ title: 'Open discussion', metrics: [], summary: 'They talked.' }, labels)).toBe(
      '# Open discussion\n\n' +
      '## Summary\n\n' +
      'They talked.'
    );
  });

  it('throws when a metric series has no values', () => {
    const bad: ReportInput = {
      title: 'X',
      metrics: [{ name: 'score', series: [{ agentId: 'a', agentName: 'Alice', values: [] }] }],
      summary: null,
    };
    expect(() => generateMarkdownReport(bad, labels)).toThrow();
  });

  it('throws when title is empty', () => {
    expect(() => generateMarkdownReport({ ...baseInput, title: '' }, labels)).toThrow();
  });
});
