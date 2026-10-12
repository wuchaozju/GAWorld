import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ExportSection } from './ExportSection';

const labels = { csv: 'Export CSV', markdown: 'Export report' };

describe('ExportSection', () => {
  it('calls onExportCsv when the CSV button is clicked', () => {
    const onExportCsv = vi.fn();
    render(<ExportSection onExportCsv={onExportCsv} onExportMarkdown={() => {}} labels={labels} />);
    fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    expect(onExportCsv).toHaveBeenCalledTimes(1);
  });

  it('calls onExportMarkdown when the report button is clicked', () => {
    const onExportMarkdown = vi.fn();
    render(<ExportSection onExportCsv={() => {}} onExportMarkdown={onExportMarkdown} labels={labels} />);
    fireEvent.click(screen.getByRole('button', { name: 'Export report' }));
    expect(onExportMarkdown).toHaveBeenCalledTimes(1);
  });
});
