// This file shows a results summary area with a button, an error message, and a summary message.
// AiSummarySection shows the button text from the labels it is given, shows an error when there is one,
// and shows the summary only when a summary exists and loading has finished.
import React from 'react';

interface AiSummarySectionProps {
  summary: string | null;
  isGenerating: boolean;
  error: string | null;
  onGenerate: () => void;
  labels: {
    generate: string;
    generating: string;
  };
}

export function AiSummarySection({
  summary,
  isGenerating,
  error,
  onGenerate,
  labels,
}: AiSummarySectionProps): React.JSX.Element {
  return (
    <section>
      <button
        type="button"
        onClick={onGenerate}
        disabled={isGenerating}
        className="flex items-center gap-2 px-4 py-2 rounded-lg border text-sm font-medium transition-colors hover:opacity-80 disabled:opacity-50"
        style={{ background: 'var(--ss-brand-soft)', color: 'var(--ss-brand-primary)', borderColor: 'var(--ss-brand-primary)' }}
      >
        {isGenerating ? labels.generating : labels.generate}
      </button>
      {error !== null ? <p role="alert" className="mt-2 text-sm" style={{ color: 'var(--color-text-error, #ef4444)' }}>{error}</p> : null}
      {summary !== null && !isGenerating ? <div className="mt-3 text-sm leading-relaxed" style={{ color: 'var(--ss-workspace-text)', whiteSpace: 'pre-wrap' }}>{summary}</div> : null}
    </section>
  );
}
