import { describe, it, expect } from 'vitest';
import { buildSummaryPrompt } from './summaryPrompt';
import type { SummaryPromptInput } from './summaryPrompt';
import type { MetricAggregatePoint, Series } from './resultsComputations';

const base: SummaryPromptInput = {
  title: 'Public goods game',
  language: 'en',
  metrics: [
    { name: 'score', series: [
      { agentId: 'a', agentName: 'Alice', values: [10, 12, 15] },
      { agentId: 'b', agentName: 'Bob', values: [8, 9, 9] },
    ] },
  ],
};

describe('buildSummaryPrompt', () => {
  it('includes the title, the English instruction, and each agent\'s real values with final', () => {
    const p = buildSummaryPrompt(base);
    expect(p).toContain('Public goods game');
    expect(p).toContain('English');
    expect(p).toContain('score:');
    expect(p).toContain('- Alice: 10, 12, 15 (final: 15)');
    expect(p).toContain('- Bob: 8, 9, 9 (final: 9)');
  });

  it('switches the instruction language to Chinese when language is zh', () => {
    const p = buildSummaryPrompt({ ...base, language: 'zh' });
    expect(p).toContain('中文');
    expect(p).toContain('- Alice: 10, 12, 15 (final: 15)');
  });

  it('throws when metrics is empty', () => {
    expect(() => buildSummaryPrompt({ ...base, metrics: [] })).toThrow();
  });

  it('throws when a series has no values', () => {
    expect(() => buildSummaryPrompt({
      ...base,
      metrics: [{ name: 'score', series: [{ agentId: 'a', agentName: 'Alice', values: [] }] }],
    })).toThrow();
  });

  it('throws when title is empty', () => {
    expect(() => buildSummaryPrompt({ ...base, title: '' })).toThrow();
  });

  it('uses aggregate statistics format when series count exceeds 12', () => {
    const many: Series[] = Array.from({ length: 13 }, (_, i) => ({
      agentId: `a${i}`,
      agentName: `Agent${i + 1}`,
      values: [10 + i, 12 + i, 14 + i],
    }));
    const prompt = buildSummaryPrompt({
      title: 'Test',
      language: 'en',
      metrics: [{ name: 'payoff', series: many }],
    });
    expect(prompt.toLowerCase()).toContain('mean');
    expect(prompt.toLowerCase()).toContain('min');
    expect(prompt.toLowerCase()).toContain('max');
    expect(prompt).not.toContain('Agent1');
  });

  it('stays in per-agent format when series count is at or below 12', () => {
    const few: Series[] = Array.from({ length: 12 }, (_, i) => ({
      agentId: `a${i}`,
      agentName: `Agent${i + 1}`,
      values: [10, 12],
    }));
    const prompt = buildSummaryPrompt({
      title: 'Test',
      language: 'en',
      metrics: [{ name: 'payoff', series: few }],
    });
    expect(prompt).toContain('Agent1');
  });

  it('instructs the model to return plain prose without a JSON or markdown wrapper', () => {
    const series = [{ agentId: 'a', agentName: 'Alice', values: [10, 12] }];
    const prompt = buildSummaryPrompt({
      title: 'T', language: 'en',
      metrics: [{ name: 'payoff', series }],
    });
    expect(prompt).toMatch(/plain|no.?json|no.?markdown/i);
  });
});
