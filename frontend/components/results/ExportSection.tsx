/*
This file shows two export buttons.
ExportSection displays one button for CSV export and one button for markdown export, and each button calls the matching function it was given.
*/

import React from 'react';

interface ExportSectionProps {
  onExportCsv: () => void;
  onExportMarkdown: () => void;
  labels: {
    csv: string;
    markdown: string;
  };
}

export function ExportSection({
  onExportCsv,
  onExportMarkdown,
  labels,
}: ExportSectionProps): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
      <button type="button" onClick={onExportCsv}>
        {labels.csv}
      </button>
      <button type="button" onClick={onExportMarkdown}>
        {labels.markdown}
      </button>
    </div>
  );
}
