/**
 * Agent panel with virtualized scrolling for large agent lists.
 *
 * Uses @tanstack/react-virtual to render only visible agents,
 * supporting 1000+ agents without performance degradation.
 * Includes search toolbar for quick agent lookup.
 *
 * Exports: AgentPanel
 */

import { useState, useRef, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Search } from 'lucide-react';
import { useSimulationStore } from '../store';
import { AgentCard } from './AgentCard';

export const AgentPanel: React.FC = () => {
  const { t } = useTranslation();
  const agents = useSimulationStore(state => state.agents);
  const [search, setSearch] = useState('');
  const parentRef = useRef<HTMLDivElement>(null);

  const filteredAgents = useMemo(() => {
    if (!search.trim()) return agents;
    const q = search.toLowerCase();
    return agents.filter(a => a.name.toLowerCase().includes(q));
  }, [agents, search]);

  const virtualizer = useVirtualizer({
    count: filteredAgents.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 108,
    overscan: 5,
    measureElement: (el) => el?.getBoundingClientRect().height ?? 108,
  });

  return (
    <div className="h-full flex flex-col" style={{ background: 'var(--ss-workspace-surface)' }}>
      {/* Search toolbar */}
      <div className="p-3 border-b" style={{ borderColor: 'var(--ss-workspace-border)' }}>
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg"
          style={{ background: 'var(--ss-workspace-surface-alt)', border: '1px solid var(--ss-workspace-border)' }}>
          <Search size={14} style={{ color: 'var(--ss-workspace-muted)' }} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('components.agentPanel.searchPlaceholder', { defaultValue: '搜索智能体、角色或模型…' })}
            className="flex-1 bg-transparent text-sm outline-none"
            style={{ color: 'var(--ss-workspace-heading)' }}
          />
          <span className="text-xs" style={{ color: 'var(--ss-workspace-muted)' }}>
            {filteredAgents.length}/{agents.length}
          </span>
        </div>
      </div>

      {/* Virtualized list */}
      <div ref={parentRef} className="flex-1 overflow-y-auto">
        <div style={{ height: `${virtualizer.getTotalSize()}px`, width: '100%', position: 'relative' }}>
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const agent = filteredAgents[virtualRow.index];
            return (
              <div
                key={agent.id}
                ref={virtualizer.measureElement}
                data-index={virtualRow.index}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              >
                <AgentCard agent={agent} />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
