/**
 * Log viewer component with timeline, card, and list views.
 *
 * Displays simulation events including agent actions, dialogue, and system events.
 * Supports filtering by type and agent, with search functionality.
 * In timeline view, displays custom action and resource names from scenario params.
 *
 * Exports: LogViewer (default export)
 */

import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useSimulationStore } from '../store';
import { useTranslation } from 'react-i18next';
import { LogEntry, ViewMode } from '../types';
import { ChevronDown, Search, X, Check, Image as ImageIcon } from 'lucide-react';
import { getActionConfig, getResourceName } from '../utils/scenarioHelpers';
import { buildRoundProgressMap, getLatestRoundProgress } from '../utils/logProgress';
import { WorkspaceRunControls } from './WorkspaceRunControls';

type DiffOp<T> = {
  type: 'equal' | 'add' | 'remove';
  value: T;
};

type PolicyDiffRow = {
  kind: 'unchanged' | 'added' | 'removed' | 'modified';
  left: string;
  right: string;
};

type InlineDiffSegment = {
  kind: 'unchanged' | 'added' | 'removed';
  text: string;
};

const splitDiffText = (text: string): string[] =>
  String(text || '')
    .split('\n')
    .map(line => line.trimEnd())
    .filter(line => line.trim().length > 0);

const buildDiffOps = <T,>(left: T[], right: T[], isEqual: (a: T, b: T) => boolean): DiffOp<T>[] => {
  const dp: number[][] = Array.from({ length: left.length + 1 }, () => Array(right.length + 1).fill(0));

  for (let i = left.length - 1; i >= 0; i -= 1) {
    for (let j = right.length - 1; j >= 0; j -= 1) {
      if (isEqual(left[i], right[j])) {
        dp[i][j] = dp[i + 1][j + 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
  }

  const ops: DiffOp<T>[] = [];
  let i = 0;
  let j = 0;

  while (i < left.length && j < right.length) {
    if (isEqual(left[i], right[j])) {
      ops.push({ type: 'equal', value: left[i] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ type: 'remove', value: left[i] });
      i += 1;
    } else {
      ops.push({ type: 'add', value: right[j] });
      j += 1;
    }
  }

  while (i < left.length) {
    ops.push({ type: 'remove', value: left[i] });
    i += 1;
  }

  while (j < right.length) {
    ops.push({ type: 'add', value: right[j] });
    j += 1;
  }

  return ops;
};

const buildPolicyDiffRows = (leftText: string, rightText: string): PolicyDiffRow[] => {
  const leftLines = splitDiffText(leftText);
  const rightLines = splitDiffText(rightText);
  const ops = buildDiffOps(leftLines, rightLines, (a, b) => a === b);
  const rows: PolicyDiffRow[] = [];
  let removedGroup: string[] = [];
  let addedGroup: string[] = [];

  const flushGroups = () => {
    const count = Math.max(removedGroup.length, addedGroup.length);
    for (let idx = 0; idx < count; idx += 1) {
      const left = removedGroup[idx] || '';
      const right = addedGroup[idx] || '';
      if (left && right) {
        rows.push({ kind: 'modified', left, right });
      } else if (left) {
        rows.push({ kind: 'removed', left, right: '' });
      } else if (right) {
        rows.push({ kind: 'added', left: '', right });
      }
    }
    removedGroup = [];
    addedGroup = [];
  };

  ops.forEach(op => {
    if (op.type === 'equal') {
      flushGroups();
      rows.push({ kind: 'unchanged', left: String(op.value), right: String(op.value) });
      return;
    }
    if (op.type === 'remove') {
      removedGroup.push(String(op.value));
      return;
    }
    addedGroup.push(String(op.value));
  });

  flushGroups();
  return rows;
};

const buildInlineDiffSegments = (leftText: string, rightText: string, side: 'left' | 'right'): InlineDiffSegment[] => {
  const leftChars = Array.from(leftText || '');
  const rightChars = Array.from(rightText || '');
  const ops = buildDiffOps(leftChars, rightChars, (a, b) => a === b);
  const segments: InlineDiffSegment[] = [];

  const pushSegment = (kind: InlineDiffSegment['kind'], text: string) => {
    if (!text) {
      return;
    }
    const last = segments[segments.length - 1];
    if (last && last.kind === kind) {
      last.text += text;
      return;
    }
    segments.push({ kind, text });
  };

  ops.forEach(op => {
    if (op.type === 'equal') {
      pushSegment('unchanged', String(op.value));
      return;
    }
    if (side === 'left' && op.type === 'remove') {
      pushSegment('removed', String(op.value));
      return;
    }
    if (side === 'right' && op.type === 'add') {
      pushSegment('added', String(op.value));
    }
  });

  return segments;
};

const inlineSegmentClassName = (kind: InlineDiffSegment['kind']) => {
  if (kind === 'added') {
    return 'bg-emerald-200/70 text-emerald-900 rounded px-0.5';
  }
  if (kind === 'removed') {
    return 'bg-rose-200/70 text-rose-900 rounded px-0.5';
  }
  return '';
};

const diffCellClassName = (kind: PolicyDiffRow['kind'], side: 'left' | 'right') => {
  if (kind === 'modified') {
    return 'border-amber-200 bg-amber-50/80';
  }
  if (kind === 'removed' && side === 'left') {
    return 'border-rose-200 bg-rose-50';
  }
  if (kind === 'added' && side === 'right') {
    return 'border-emerald-200 bg-emerald-50';
  }
  return 'border-transparent bg-transparent';
};

const PolicyDiffCard: React.FC<{ entry: LogEntry }> = ({ entry }) => {
  const { t } = useTranslation();
  const data = entry.structuredData;
  const showDraftExpanded = import.meta.env.DEV;
  const rows = useMemo(
    () => buildPolicyDiffRows(data?.leftContent || '', data?.rightContent || ''),
    [data?.leftContent, data?.rightContent]
  );

  if (!data || data.kind !== 'policy_diff') {
    return null;
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {data.agentLabel && <span className="text-sm font-semibold" style={{ color: 'var(--ss-workspace-heading)' }}>{data.agentLabel}</span>}
        <span className="text-sm font-semibold" style={{ color: 'var(--ss-workspace-heading)' }}>{data.title}</span>
      </div>

      <div className="text-xs" style={{ color: 'var(--ss-workspace-muted)' }}>
        {t('simulation.log.diff.description')}
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--ss-workspace-border)', background: 'var(--ss-surface-strong)' }}>
          <div className="border-b px-3 py-2 text-xs font-semibold uppercase tracking-wide" style={{ borderColor: 'var(--ss-workspace-border)', background: 'var(--ss-surface-inset)', color: 'var(--ss-workspace-text)' }}>
            {data.leftTitle}
          </div>
          <div className="max-h-80 overflow-auto px-3 py-3 text-sm leading-6 space-y-1" style={{ color: 'var(--ss-workspace-heading)' }}>
            {rows.filter(row => row.left).map((row, idx) => {
              const segments = row.kind === 'modified'
                ? buildInlineDiffSegments(row.left, row.right, 'left')
                : [];
              return (
                <div
                  key={`left-${idx}`}
                  className={`rounded px-2 py-1 whitespace-pre-wrap break-words border ${diffCellClassName(row.kind, 'left')}`}
                >
                  {row.kind === 'modified' ? (
                    segments.map((segment, segmentIdx) => (
                      <span key={`left-${idx}-${segmentIdx}`} className={inlineSegmentClassName(segment.kind)}>
                        {segment.text}
                      </span>
                    ))
                  ) : (
                    row.left
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="rounded-lg border border-blue-200 bg-blue-50 overflow-hidden">
          <div className="border-b border-blue-200 bg-blue-100 px-3 py-2 text-xs font-semibold text-blue-700 uppercase tracking-wide">
            {data.rightTitle}
          </div>
          <div className="max-h-80 overflow-auto px-3 py-3 text-sm leading-6 space-y-1" style={{ color: 'var(--ss-workspace-heading)' }}>
            {rows.filter(row => row.right).map((row, idx) => {
              const segments = row.kind === 'modified'
                ? buildInlineDiffSegments(row.left, row.right, 'right')
                : [];
              return (
                <div
                  key={`right-${idx}`}
                  className={`rounded px-2 py-1 whitespace-pre-wrap break-words border ${diffCellClassName(row.kind, 'right')}`}
                >
                  {row.kind === 'modified' ? (
                    segments.map((segment, segmentIdx) => (
                      <span key={`right-${idx}-${segmentIdx}`} className={inlineSegmentClassName(segment.kind)}>
                        {segment.text}
                      </span>
                    ))
                  ) : (
                    row.right
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {data.draftContent && (
        <details
          open={showDraftExpanded}
          className="rounded-lg border overflow-hidden group"
          style={{ borderColor: 'var(--ss-workspace-border)', background: 'var(--ss-workspace-surface)' }}
        >
          <summary className="flex cursor-pointer list-none items-center justify-between border-b px-3 py-2 text-xs font-semibold uppercase tracking-wide" style={{ borderColor: 'var(--ss-workspace-border)', background: 'var(--ss-surface-strong)', color: 'var(--ss-workspace-text)' }}>
            <span>{data.draftTitle}</span>
            <span className="text-[11px] font-medium normal-case tracking-normal group-open:hidden" style={{ color: 'var(--ss-workspace-muted)' }}>
              {t('simulation.log.diff.debugExpand')}
            </span>
            <span className="hidden text-[11px] font-medium normal-case tracking-normal group-open:inline" style={{ color: 'var(--ss-workspace-muted)' }}>
              {t('simulation.log.diff.debugCollapse')}
            </span>
          </summary>
          <div className="max-h-64 overflow-auto px-3 py-3 text-sm leading-6 whitespace-pre-wrap break-words" style={{ color: 'var(--ss-workspace-heading)' }}>
            {data.draftContent}
          </div>
        </details>
      )}

      <div className="flex flex-wrap gap-2 text-xs" style={{ color: 'var(--ss-workspace-muted)' }}>
        <span className="rounded-full bg-emerald-100 px-2 py-1 text-emerald-700">{t('simulation.log.diff.added')}</span>
        <span className="rounded-full bg-rose-100 px-2 py-1 text-rose-700">{t('simulation.log.diff.removed')}</span>
        <span className="rounded-full bg-amber-100 px-2 py-1 text-amber-700">{t('simulation.log.diff.modified')}</span>
      </div>

      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
        <div className="font-medium">{data.reasonLabel}{t('common.colon')}</div>
        <div className="mt-1 whitespace-pre-wrap break-words">{data.reason}</div>
      </div>

      <div className="text-xs whitespace-pre-wrap break-words" style={{ color: 'var(--ss-workspace-muted)' }}>
        <span className="font-medium">{data.metricsLabel}{t('common.colon')}</span>
        {data.metrics}
      </div>
    </div>
  );
};

// Helper for displaying time niceliy
const formatLogTime = (dateStr: string) => {
  if (!dateStr || dateStr.length < 10) return dateStr;
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return dateStr;

  // E.g. "Mar 10, 14:00"
  return date.toLocaleString('zh-CN', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
  });
};

// Resolve action name for display using scenario params
const getDisplayActionName = (
  action: string,
  scenarioParams: Record<string, unknown>
): string => {
  // Map original action names to custom names for stag hunt / battle of sexes scenarios
  const originalActions = ['Opera', 'Football', 'Stag', 'Hare'];

  if (originalActions.includes(action)) {
    // Determine action index based on original position
    // Opera/Stag are action 1, Football/Hare are action 2
    const actionIndex = ['Opera', 'Stag'].includes(action) ? 1 : 2;
    const config = getActionConfig(scenarioParams, actionIndex);
    return config.name;
  }

  return action;
};

// Format public goods contribution event with custom resource/action names
const formatPublicGoodsEvent = (
  eventContent: string,
  scenarioParams: Record<string, unknown>,
  t: (key: string, options?: Record<string, unknown>) => string
): string => {
  const resource = getResourceName(scenarioParams);
  const actionName = (scenarioParams.action_name as string) || 'Contribute';

  // Try to parse contribution amount from content
  const contributionMatch = eventContent.match(/(\d+)/);
  if (contributionMatch) {
    const amount = contributionMatch[1];
    // Extract agent name if present
    const agentMatch = eventContent.match(/^([^:]+):/);
    const agentName = agentMatch ? agentMatch[1].trim() : '';

    if (agentName) {
      return t('simulation.log.public_goods_contribution', {
        agent: agentName,
        action: actionName.toLowerCase(),
        amount: amount,
        resource: resource.toLowerCase(),
      });
    }
  }

  return eventContent;
};

const LogItem: React.FC<{
  entry: LogEntry;
  mode: ViewMode;
  nodeWorldTime?: string;
  agents?: any[];
  scenarioParams?: Record<string, unknown>;
}> = ({ entry, mode, nodeWorldTime, agents = [], scenarioParams = {} }) => {
  const { t } = useTranslation();
  const [isImageExpanded, setIsImageExpanded] = useState(false);

  const getBorderColor = () => {
    switch (entry.type) {
      case 'AGENT_SAY': return 'border-l-blue-500';
      case 'AGENT_ACTION': return 'border-l-amber-500';
      case 'AGENT_METADATA': return 'border-l-purple-400';
      case 'ENVIRONMENT': return 'border-l-emerald-500';
      default: return '';
    }
  };

  const getBorderStyle = (): React.CSSProperties | undefined => {
    switch (entry.type) {
      case 'AGENT_SAY':
      case 'AGENT_ACTION':
      case 'AGENT_METADATA':
      case 'ENVIRONMENT':
        return undefined;
      default:
        return { borderLeftColor: 'var(--ss-workspace-border)' };
    }
  };

  const getBadgeColor = (): { className: string; style?: React.CSSProperties } => {
    switch (entry.type) {
      case 'SYSTEM': return { className: '', style: { background: 'var(--ss-surface-inset)', color: 'var(--ss-workspace-text)' } };
      case 'AGENT_SAY': return { className: 'bg-blue-50 text-blue-600' };
      case 'AGENT_ACTION': return { className: 'bg-amber-50 text-amber-600' };
      case 'AGENT_METADATA': return { className: 'bg-purple-50 text-purple-600' };
      case 'ENVIRONMENT': return { className: 'bg-emerald-50 text-emerald-600' };
      default: return { className: '', style: { background: 'var(--ss-surface-inset)', color: 'var(--ss-workspace-muted)' } };
    }
  };

  const translateType = (type: string, agentId?: string) => {
    switch(type) {
      case 'SYSTEM': return t('components.logViewer.typeSystem');
      case 'AGENT_SAY': return t('components.logViewer.typeDialogue');
      case 'AGENT_ACTION': return t('components.logViewer.typeAction');
      case 'AGENT_METADATA':
        // For AGENT_METADATA, show Agent name instead of "system"
        if (agentId && agents.length > 0) {
          const agent = agents.find(a => a.id === agentId);
          return agent ? agent.name : t('components.logViewer.typeAgentMetadata');
        }
        return t('components.logViewer.typeAgentMetadata');
      case 'ENVIRONMENT': return t('components.logViewer.typeEnvironment');
      default: return type;
    }
  };

  // Use entry timestamp if valid, otherwise fallback or node time
  const displayTime = entry.timestamp.includes('-') ? formatLogTime(entry.timestamp) : entry.timestamp;

  // Process content to replace action names with custom names
  const getProcessedContent = (content: string): string => {
    if (!content || Object.keys(scenarioParams).length === 0) {
      return content;
    }

    let processedContent = content;

    // Handle stag hunt / battle of sexes action names
    // Match patterns like "chose Opera", "chose Stag", "chose Football", "chose Hare"
    const actionChoicePattern = /(chose|选择了)\s+(Opera|Football|Stag|Hare)/gi;
    processedContent = processedContent.replace(actionChoicePattern, (match, verb, action) => {
      const displayName = getDisplayActionName(action, scenarioParams);
      return `${verb} ${displayName}`;
    });

    // Handle action names in patterns like "performed Opera action", "Opera action"
    const actionNamePattern = /\b(Opera|Football|Stag|Hare)\b/g;
    processedContent = processedContent.replace(actionNamePattern, (match) => {
      return getDisplayActionName(match, scenarioParams);
    });

    // Handle public goods contribution events
    if (scenarioParams.resource_name || scenarioParams.action_name) {
      // Check if this looks like a contribution message
      if (content.toLowerCase().includes('contribut') ||
          content.toLowerCase().includes('贡献') ||
          /\b\d+\s*(tokens?|tokens)\b/i.test(content)) {
        processedContent = formatPublicGoodsEvent(content, scenarioParams, t);
      }
    }

    return processedContent;
  };

  const displayContent = getProcessedContent(entry.content);
  const hasPolicyDiff = entry.structuredData?.kind === 'policy_diff';

  const ImageComponent = () => (
    entry.imageUrl ? (
      <div className="mt-2">
        <div
          className="relative group cursor-pointer w-fit"
          onClick={() => setIsImageExpanded(true)}
        >
          <img
            src={entry.imageUrl}
            alt={t('components.logViewer.logAttachment')}
            className="max-h-48 rounded border object-cover"
            style={{ borderColor: 'var(--ss-workspace-border)' }}
          />
          <div className="absolute inset-0 bg-black/10 group-hover:bg-black/20 transition-colors rounded flex items-center justify-center opacity-0 group-hover:opacity-100">
             <ImageIcon className="text-white drop-shadow-md" size={24} />
          </div>
        </div>

        {/* Simple Lightbox */}
        {isImageExpanded && (
          <div className="fixed inset-0 z-[100] bg-black/80 flex items-center justify-center p-4" onClick={(e) => {
             e.stopPropagation();
             setIsImageExpanded(false);
          }}>
             <img src={entry.imageUrl} alt={t('components.logViewer.fullSize')} className="max-w-full max-h-full rounded shadow-2xl" />
             <button className="absolute top-4 right-4 text-white hover:text-slate-300">
               <X size={32} />
             </button>
          </div>
        )}
      </div>
    ) : null
  );

  const MediaBadges = () => (
    <div className="flex flex-wrap gap-2 mt-2 text-[11px]" style={{ color: 'var(--ss-workspace-muted)' }}>
      {entry.audioUrl && (
        <a href={entry.audioUrl} target="_blank" rel="noreferrer" className="px-2 py-1 rounded" style={{ background: 'var(--ss-surface-inset)' }}>
          {t('components.logViewer.audioLink')}
        </a>
      )}
      {entry.videoUrl && (
        <a href={entry.videoUrl} target="_blank" rel="noreferrer" className="px-2 py-1 rounded" style={{ background: 'var(--ss-surface-inset)' }}>
          {t('components.logViewer.videoLink')}
        </a>
      )}
    </div>
  );

  if (mode === ViewMode.LIST) {
    return (
      <div className={`py-2 px-4 border-b text-sm flex gap-4 ${entry.type === 'SYSTEM' ? '' : ''}`} style={entry.type === 'SYSTEM' ? { background: 'var(--ss-surface-strong)' } : undefined}>
        <span className="font-mono text-xs w-24 shrink-0 whitespace-nowrap" style={{ color: 'var(--ss-workspace-muted)' }}>{displayTime}</span>
        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded uppercase self-start whitespace-nowrap ${getBadgeColor().className}`} style={getBadgeColor().style}>
          {translateType(entry.type, entry.agentId)}
        </span>
        <div className="flex-1">
          {/* For AGENT_METADATA, don't repeat agentId since it's already shown in the badge */}
          {entry.agentId && entry.type !== 'AGENT_METADATA' && (
            <span className="font-bold mr-2" style={{ color: 'var(--ss-workspace-heading)' }}>{entry.agentId}:</span>
          )}
          {hasPolicyDiff ? (
            <PolicyDiffCard entry={entry} />
          ) : (
            <span style={{ color: 'var(--ss-workspace-text)' }}>{displayContent}</span>
          )}
          <ImageComponent />
          <MediaBadges />
        </div>
      </div>
    );
  }

  // Card & Timeline Views
  return (
    <div className={`mb-3 p-3 border rounded shadow-sm relative ${getBorderColor()} border-l-4 hover:shadow-md transition-shadow`} style={{ background: 'var(--ss-workspace-surface)', ...getBorderStyle() }}>
       {mode === ViewMode.TIMELINE && (
         <div className="absolute -left-[29px] top-4 w-3 h-3 rounded-full border-2 z-10" style={{ background: 'var(--ss-surface-inset)', borderColor: 'var(--ss-surface-strong)' }}></div>
       )}
      <div className="flex justify-between items-start mb-2">
        <div className="flex items-center gap-2">
           <span className={`text-[10px] font-bold px-2 py-0.5 rounded uppercase ${getBadgeColor().className}`} style={getBadgeColor().style}>
            {translateType(entry.type, entry.agentId)}
          </span>
          {/* For AGENT_METADATA, don't repeat agentId since it's already shown in the badge */}
          {entry.agentId && entry.type !== 'AGENT_METADATA' && (
            <span className="text-xs font-bold" style={{ color: 'var(--ss-workspace-heading)' }}>{entry.agentId}</span>
          )}
        </div>
        <span className="text-[10px] font-mono" style={{ color: 'var(--ss-workspace-muted)' }}>{displayTime}</span>
      </div>
      {hasPolicyDiff ? (
        <PolicyDiffCard entry={entry} />
      ) : (
        <p className="text-sm leading-relaxed whitespace-pre-line" style={{ color: 'var(--ss-workspace-heading)' }}>{displayContent}</p>
      )}
      <ImageComponent />
      <MediaBadges />
    </div>
  );
};

export const LogViewer: React.FC = () => {
  const { t } = useTranslation();
  const logs = useSimulationStore(state => state.logs);
  const nodes = useSimulationStore(state => state.nodes);
  const selectedNodeId = useSimulationStore(state => state.selectedNodeId);
  const agents = useSimulationStore(state => state.agents);
  const currentSimulation = useSimulationStore(state => state.currentSimulation);

  // Extract scenario params from current simulation's scene_config
  const scenarioParams = useMemo((): Record<string, unknown> => {
    const sceneConfig = currentSimulation?.scene_config || {};
    // Parameters may be nested under 'parameters' or at the top level
    return (sceneConfig.parameters as Record<string, unknown>) || sceneConfig || {};
  }, [currentSimulation]);

  const viewMode = ViewMode.CARD as ViewMode;
  const [searchQuery, setSearchQuery] = useState('');
  const [openRounds, setOpenRounds] = useState<Set<number>>(new Set());
  const hasInitializedOpenRoundsRef = useRef(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const logItemRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const previousSelectedNodeIdRef = useRef<string | null>(selectedNodeId);

  // Compute Ancestry Path for current selection
  const ancestorIds = useMemo(() => {
    const ids = new Set<string>();
    let current = nodes.find(n => n.id === selectedNodeId);
    while (current) {
      ids.add(current.id);
      current = nodes.find(n => n.id === current.parentId);
    }
    return ids;
  }, [nodes, selectedNodeId]);

  // Debug: Detect duplicate event IDs in incoming logs (Task 1: BUG-UI-02 investigation)
  useEffect(() => {
    const ids = logs.map(l => l.id);
    const uniqueIds = new Set(ids);
    if (ids.length !== uniqueIds.size) {
      console.warn('Duplicate event IDs detected:', {
        total: ids.length,
        unique: uniqueIds.size,
        duplicates: ids.filter((id, idx) => ids.indexOf(id) !== idx)
      });
    }
  }, [logs]);

  const pathLogs = useMemo(() => {
    const seenIds = new Set<string>();

    return logs.filter(log => {
      if (seenIds.has(log.id)) {
        console.warn(`Duplicate event filtered: ${log.id}`);
        return false;
      }
      seenIds.add(log.id);

      if (log.nodeId && !ancestorIds.has(log.nodeId)) {
        return false;
      }

      return true;
    });
  }, [logs, ancestorIds]);

  // Filter Logic with deduplication (BUG-UI-02 fix)
  const filteredLogs = useMemo(() => {
    return pathLogs.filter(log => {
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        const contentMatch = log.content.toLowerCase().includes(query);
        const agentMatch = log.agentId?.toLowerCase().includes(query);
        const typeMatch = log.type.toLowerCase().includes(query);
        if (!contentMatch && !agentMatch && !typeMatch) return false;
      }

      return true;
    });
  }, [pathLogs, searchQuery]);

  const logGroups = useMemo(() => {
    const groups = new Map<number, LogEntry[]>();
    filteredLogs.forEach((log) => {
      const round = typeof log.round === 'number' ? log.round : 0;
      if (!groups.has(round)) {
        groups.set(round, []);
      }
      groups.get(round)!.push(log);
    });
    return Array.from(groups.entries())
      .sort((left, right) => left[0] - right[0])
      .map(([round, entries]) => ({ round, entries }));
  }, [filteredLogs]);

  const pathLogGroups = useMemo(() => {
    const groups = new Map<number, LogEntry[]>();
    pathLogs.forEach((log) => {
      const round = typeof log.round === 'number' ? log.round : 0;
      if (!groups.has(round)) {
        groups.set(round, []);
      }
      groups.get(round)!.push(log);
    });
    return Array.from(groups.entries())
      .sort((left, right) => left[0] - right[0])
      .map(([round, entries]) => ({ round, entries }));
  }, [pathLogs]);

  const progressByRound = useMemo(
    () => buildRoundProgressMap(pathLogGroups, agents.length),
    [pathLogGroups, agents.length],
  );

  const latestRoundProgress = useMemo(
    () => getLatestRoundProgress(pathLogGroups, agents.length),
    [pathLogGroups, agents.length],
  );

  const progressLabel = useMemo(() => {
    if (!latestRoundProgress || latestRoundProgress.totalAgents <= 0) {
      return null;
    }

    const stepLabel = latestRoundProgress.round <= 0
      ? t('components.logViewer.setupGroup', { defaultValue: 'Setup' })
      : t('components.logViewer.stepGroup', {
          step: latestRoundProgress.round,
          defaultValue: `Step ${latestRoundProgress.round}`,
        });
    const agentProgress = t('components.logViewer.agentOutputProgress', {
      finished: latestRoundProgress.finishedAgents,
      total: latestRoundProgress.totalAgents,
      defaultValue: `${latestRoundProgress.finishedAgents} of ${latestRoundProgress.totalAgents} agents reported`,
    });

    return `${stepLabel} - ${agentProgress}`;
  }, [latestRoundProgress, t]);

  useEffect(() => {
    if (logGroups.length === 0) {
      setOpenRounds(new Set());
      hasInitializedOpenRoundsRef.current = false;
      return;
    }

    if (!hasInitializedOpenRoundsRef.current) {
      hasInitializedOpenRoundsRef.current = true;
      setOpenRounds(new Set([logGroups[0].round]));
      return;
    }

    const availableRounds = new Set(logGroups.map((group) => group.round));
    setOpenRounds((currentRounds) => {
      const nextRounds = new Set(
        Array.from(currentRounds).filter((round) => availableRounds.has(round)),
      );

      if (nextRounds.size === 0 && logGroups.length > 0) {
        nextRounds.add(logGroups[0].round);
      }

      return nextRounds;
    });
  }, [logGroups]);

  // When the selected node changes, jump to that node's first visible log entry.
  // Otherwise keep the existing behavior of following new logs to the bottom.
  useEffect(() => {
    const nodeChanged = previousSelectedNodeIdRef.current !== selectedNodeId;
    previousSelectedNodeIdRef.current = selectedNodeId;

    if (nodeChanged && selectedNodeId) {
      const targetLog = filteredLogs.find(log => log.nodeId === selectedNodeId);
      const targetElement = targetLog ? logItemRefs.current[targetLog.id] : null;
      if (targetElement) {
        targetElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }
    }

    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filteredLogs, selectedNodeId]);

  const clearFilters = () => {
    setSearchQuery('');
  };

  const hasActiveFilters = Boolean(searchQuery);

  return (
    <div className="flex flex-col h-full border rounded-lg overflow-hidden relative" style={{ background: 'var(--ss-surface-strong)' }}>
      {/* Toolbar */}
      <div className="border-b px-4 py-2 flex flex-col gap-2 shrink-0 z-20" style={{ background: 'var(--ss-workspace-surface)' }}>
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center gap-2 flex-1 justify-end xl:order-2">
            <WorkspaceRunControls progressLabel={progressLabel} compact />
          </div>
          <div className="flex items-center gap-2 flex-1 justify-end xl:order-1">
            <div className="relative w-full min-w-[180px] max-w-[220px]">
              <input
                type="text"
                placeholder={t('components.logViewer.searchPlaceholder')}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full py-1.5 text-xs border rounded focus:ring-1 focus:ring-brand-500 outline-none transition-all"
                style={{
                  background: 'var(--ss-surface-strong)',
                  paddingLeft: '2.875rem',
                  paddingRight: '2.25rem',
                  minHeight: '2.25rem',
                }}
              />
              <Search
                data-testid="log-search-icon"
                size={12}
                className="absolute top-1/2 -translate-y-1/2"
                style={{
                  color: 'var(--ss-workspace-muted)',
                  left: '0.875rem',
                  pointerEvents: 'none',
                }}
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute top-1/2 -translate-y-1/2 hover:text-slate-600"
                  style={{ color: 'var(--ss-workspace-muted)', right: '0.5rem' }}
                >
                  <X size={12} />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Content */}
      <div ref={scrollRef} className={`flex-1 overflow-y-auto p-4 scroll-smooth ${viewMode === ViewMode.TIMELINE ? 'pl-10' : ''}`}>
        {viewMode === ViewMode.TIMELINE && filteredLogs.length > 0 && (
           <div className="absolute left-[36px] top-0 bottom-0 w-0.5 -z-0" style={{ background: 'var(--ss-workspace-border)' }}></div>
        )}

        {filteredLogs.length > 0 ? (
          <div className="space-y-3">
            {logGroups.map((group) => {
              const isOpen = openRounds.has(group.round);
              const groupLabel = group.round <= 0
                ? t('components.logViewer.setupGroup', { defaultValue: 'Setup' })
                : t('components.logViewer.stepGroup', {
                    step: group.round,
                    defaultValue: `Step ${group.round}`,
                  });

              return (
                <section
                  key={`round-${group.round}`}
                  className="rounded-xl border overflow-hidden"
                  style={{
                    background: 'var(--ss-workspace-surface)',
                    borderColor: 'var(--ss-workspace-border)',
                  }}
                >
                  <button
                    type="button"
                    onClick={() => {
                      setOpenRounds((currentRounds) => {
                        const nextRounds = new Set(currentRounds);
                        if (nextRounds.has(group.round)) {
                          nextRounds.delete(group.round);
                        } else {
                          nextRounds.add(group.round);
                        }
                        return nextRounds;
                      });
                    }}
                    className="w-full flex items-center justify-between px-4 py-3 text-left"
                    style={{ background: 'var(--ss-surface-strong)' }}
                  >
                    <div>
                      <div
                        className="text-sm font-semibold"
                        style={{ color: 'var(--ss-workspace-heading)' }}
                      >
                        {groupLabel}
                      </div>
                    <div
                      className="text-[11px] mt-1"
                      style={{ color: 'var(--ss-workspace-muted)' }}
                    >
                        {[t('components.logViewer.showingRecords', {
                          count: group.entries.length,
                        }), progressByRound.has(group.round) && progressByRound.get(group.round)!.totalAgents > 0
                          ? t('components.logViewer.agentOutputProgress', {
                              finished: progressByRound.get(group.round)!.finishedAgents,
                              total: progressByRound.get(group.round)!.totalAgents,
                              defaultValue: `${progressByRound.get(group.round)!.finishedAgents} of ${progressByRound.get(group.round)!.totalAgents} agents reported`,
                            })
                            : null].filter(Boolean).join(' - ')}
                    </div>
                  </div>
                    <ChevronDown
                      size={16}
                      className={`transition-transform ${isOpen ? 'rotate-180' : ''}`}
                      style={{ color: 'var(--ss-workspace-muted)' }}
                    />
                  </button>

                  {isOpen && (
                    <div className="p-4">
                      {group.entries.map(log => {
                        const node = nodes.find(n => n.id === log.nodeId);
                        return (
                          <div
                            key={log.id}
                            ref={(element) => {
                              logItemRefs.current[log.id] = element;
                            }}
                          >
                            <LogItem
                              entry={log}
                              mode={viewMode}
                              nodeWorldTime={node?.worldTime}
                              agents={agents}
                              scenarioParams={scenarioParams}
                            />
                          </div>
                        );
                      })}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-40" style={{ color: 'var(--ss-workspace-muted)' }}>
            <Search size={32} className="mb-2 opacity-20" />
            <p className="text-sm">{t('components.logViewer.noMatchingLogs')}</p>
            {hasActiveFilters && (
              <button onClick={clearFilters} className="mt-2 text-xs text-brand-600 hover:underline">
                {t('components.logViewer.clearFilters')}
              </button>
            )}
            {!hasActiveFilters && (
               <p className="text-xs mt-1" style={{ color: 'var(--ss-workspace-muted)', opacity: 0.5 }}>{t('components.logViewer.noActivityYet')}</p>
            )}
          </div>
        )}
      </div>

      {/* Footer Info */}
      <div className="border-t px-3 py-1 text-[10px] flex justify-between" style={{ background: 'var(--ss-surface-strong)', color: 'var(--ss-workspace-muted)' }}>
        <span>{t('components.logViewer.showingRecords', { count: filteredLogs.length })}</span>
        {hasActiveFilters && <span>{t('components.logViewer.filterActive')}</span>}
      </div>
    </div>
  );
};
