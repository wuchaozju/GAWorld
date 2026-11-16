import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AiSummarySection } from './AiSummarySection';

const labels = { generate: 'Generate analysis', generating: 'Generating' };

describe('AiSummarySection', () => {
  it('shows the generate label and no summary when idle', () => {
    render(
      <AiSummarySection summary={null} isGenerating={false} error={null} onGenerate={() => {}} labels={labels} />,
    );
    expect(screen.getByRole('button').textContent).toBe('Generate analysis');
  });

  it('shows the generating label and disables the button while generating', () => {
    render(
      <AiSummarySection summary={null} isGenerating={true} error={null} onGenerate={() => {}} labels={labels} />,
    );
    const btn = screen.getByRole('button') as HTMLButtonElement;
    expect(btn.textContent).toBe('Generating');
    expect(btn.disabled).toBe(true);
  });

  it('renders the summary prose when present', () => {
    render(
      <AiSummarySection summary={'Cooperation emerged across rounds.'} isGenerating={false} error={null} onGenerate={() => {}} labels={labels} />,
    );
    expect(screen.getByText('Cooperation emerged across rounds.')).toBeTruthy();
  });

  it('renders the error message when present', () => {
    render(
      <AiSummarySection summary={null} isGenerating={false} error={'network down'} onGenerate={() => {}} labels={labels} />,
    );
    expect(screen.getByText('network down')).toBeTruthy();
  });

  it('calls onGenerate when the button is clicked', () => {
    const onGenerate = vi.fn();
    render(
      <AiSummarySection summary={null} isGenerating={false} error={null} onGenerate={onGenerate} labels={labels} />,
    );
    fireEvent.click(screen.getByRole('button'));
    expect(onGenerate).toHaveBeenCalledTimes(1);
  });
});
