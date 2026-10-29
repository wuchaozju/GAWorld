/**
 * Peek overlay for glancing at inactive tab content.
 *
 * Renders a semi-transparent side panel that slides in from the right
 * when the user hovers over an inactive tab. Dismisses on mouse leave.
 *
 * Exports: PeekOverlay
 */

import React from 'react';
import { useSimulationStore } from '../store';
import { SimTree } from './SimTree';
import { LogViewer } from './LogViewer';
import { Sidebar } from './Sidebar';

export const PeekOverlay: React.FC = () => {
  const peekTab = useSimulationStore((s) => s.peekTab);
  const setPeekTab = useSimulationStore((s) => s.setPeekTab);
  const setPeekOverlayActive = useSimulationStore((s) => s.setPeekOverlayActive);

  return (
    <div
      className={`absolute top-0 right-0 bottom-0 z-30 w-[30%] max-w-[350px]
                 backdrop-blur-sm border-l shadow-xl
                 overflow-hidden transition-transform duration-250 ease-out
                 ${peekTab ? 'translate-x-0 opacity-100' : 'translate-x-full opacity-0 pointer-events-none'}`}
      style={{ background: 'var(--ss-workspace-surface)', borderColor: 'var(--ss-workspace-border)' }}
      onMouseEnter={() => {
        // Access the store directly to keep the overlay alive while cursor is inside
        const current = useSimulationStore.getState().peekTab;
        if (current) setPeekTab(current);
        setPeekOverlayActive(true);
      }}
      onMouseLeave={() => {
        setPeekOverlayActive(false);
        setPeekTab(null);
      }}
    >
      <div className="h-full overflow-auto">
        {peekTab === 'workspace' ? (
          <div className="h-full flex gap-2 p-2">
            <div className="w-[40%]"><SimTree /></div>
            <div className="flex-1"><LogViewer /></div>
          </div>
        ) : null}
        {peekTab === 'agents' ? (
          <div className="h-full"><Sidebar /></div>
        ) : null}
      </div>
    </div>
  );
};
