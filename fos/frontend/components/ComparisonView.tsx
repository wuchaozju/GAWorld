import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSimulationStore } from '../store';
import { Activity, ArrowRight, GitCommit, GitCompareArrows, Loader2, Sparkles, User } from 'lucide-react';
import * as experimentsApi from '../services/experiments';

const truncate = (value: string, max = 260) => {
   if (value.length <= max) return value;
   return `${value.slice(0, max)}...`;
};

const stringifyValue = (value: unknown, max = 260) => {
   if (value == null) return '';
   if (typeof value === 'string') return truncate(value, max);
   return truncate(JSON.stringify(value), max);
};

const eventType = (event: any) => String(event?.type ?? event?.event_type ?? 'event');

const humanizeBackendLabel = (value: string): string => {
   const normalized = String(value || '').trim();
   if (!normalized) return '';
   return normalized
      .replace(/[_-]+/g, ' ')
      .replace(/\s+/g, ' ')
      .replace(/\b\w/g, (match) => match.toUpperCase());
};

const eventPayload = (event: any) => event?.data ?? event?.payload ?? event ?? {};

const eventMainText = (event: any) => {
   const data = eventPayload(event);
   const candidates = [
      data.content,
      data.message,
      data.text,
      data.action,
      data.reason,
      data.summary,
      data.description,
   ];
   const picked = candidates.find((item) => typeof item === 'string' && item.trim());
   return picked ? truncate(picked, 320) : stringifyValue(data, 320);
};

const countAgentFields = (agentDiffs: Record<string, Record<string, unknown>>) =>
   Object.values(agentDiffs).reduce((total, diffs) => total + Object.keys(diffs || {}).length, 0);

export const ComparisonView: React.FC = () => {
   const { t, i18n } = useTranslation();
   const isZh = i18n.language.startsWith('zh');
   const selectedNodeId = useSimulationStore(state => state.selectedNodeId);
   const compareTargetNodeId = useSimulationStore(state => state.compareTargetNodeId);
   const nodes = useSimulationStore(state => state.nodes);
   const isGenerating = useSimulationStore(state => state.isGenerating);
   const comparisonUseLLM = useSimulationStore(state => state.comparisonUseLLM);
   const setComparisonUseLLM = useSimulationStore(state => state.setComparisonUseLLM);
   const currentSimulation = useSimulationStore(state => state.currentSimulation);

   const nodeA = nodes.find(n => n.id === selectedNodeId);
   const nodeB = nodes.find(n => n.id === compareTargetNodeId);

   const [compareData, setCompareData] = useState<any | null>(null);
   const [isLoadingComparison, setIsLoadingComparison] = useState(false);
   const [fetchTrigger, setFetchTrigger] = useState(0);

   const translateEventType = (event: any) => {
      const type = eventType(event);
      switch (type) {
         case 'SYSTEM':
         case 'system_broadcast':
         case 'system_announcement':
            return t('components.logViewer.typeSystem');
         case 'AGENT_METADATA':
            return t('components.logViewer.typeAgentMetadata');
         case 'AGENT_SAY':
            return t('components.logViewer.typeDialogue');
         case 'AGENT_ACTION':
         case 'action_start':
         case 'action_end':
            return t('components.logViewer.typeAction');
         case 'ENVIRONMENT':
         case 'environment':
         case 'environment_event':
            return t('components.logViewer.typeEnvironment');
         default:
            return humanizeBackendLabel(type);
      }
   };

   useEffect(() => {
      let mounted = true;
      if (!selectedNodeId || !compareTargetNodeId) {
         setCompareData(null);
         setIsLoadingComparison(false);
         return;
      }

      setIsLoadingComparison(true);
      const timer = setTimeout(async () => {
         try {
            const simId = currentSimulation?.id;
            if (!simId) {
               setIsLoadingComparison(false);
               return;
            }
            const useLLM = Boolean(comparisonUseLLM);
            const a = Number(selectedNodeId);
            const b = Number(compareTargetNodeId);
            if (!Number.isFinite(a) || !Number.isFinite(b)) {
               const notify = useSimulationStore.getState().addNotification;
               notify('error', t('components.comparisonView.notBackendNodeError'));
               setCompareData(null);
               setIsLoadingComparison(false);
               return;
            }
            const locale = i18n.language.startsWith('zh') ? 'zh' : 'en';
            const res = await experimentsApi.compareNodes(simId, a, b, useLLM, locale);
            if (!mounted) return;
            setCompareData(res || null);
            setIsLoadingComparison(false);
         } catch (e) {
            console.error('compareNodes failed', e);
            if (mounted) {
               setCompareData(null);
               setIsLoadingComparison(false);
            }
         }
      }, 250);

      return () => {
         mounted = false;
         clearTimeout(timer);
      };
   }, [selectedNodeId, compareTargetNodeId, comparisonUseLLM, fetchTrigger, currentSimulation, isZh, t]);

   const leftEvents = compareData?.only_in_a || [];
   const rightEvents = compareData?.only_in_b || [];
   const agentDiffs = compareData?.agent_diffs || {};
   const agentDiffFieldCount = countAgentFields(agentDiffs);
   const eventTypeCount = useMemo(() => {
      const types = new Set<string>();
      leftEvents.forEach((event: any) => types.add(eventType(event)));
      rightEvents.forEach((event: any) => types.add(eventType(event)));
      return types.size;
   }, [leftEvents, rightEvents]);
   const localSummary = useMemo(() => {
      if (!compareData) return '';
      if (!leftEvents.length && !rightEvents.length && !agentDiffFieldCount) {
         return t('components.comparisonView.noVisibleDiffSummary');
      }
      if (!agentDiffFieldCount) {
         return t('components.comparisonView.eventOnlyDiffSummary', {
            left: leftEvents.length,
            right: rightEvents.length,
         });
      }
      return t('components.comparisonView.eventAndAgentDiffSummary', {
         left: leftEvents.length,
         right: rightEvents.length,
         agents: Object.keys(agentDiffs).length,
         fields: agentDiffFieldCount,
      });
   }, [agentDiffFieldCount, agentDiffs, compareData, leftEvents.length, rightEvents.length, t]);

   if (!nodeA) return <div className="p-8 text-[var(--ss-workspace-muted)]">{t('components.comparisonView.selectBaselineNode')}</div>;
   if (!nodeB) return <div className="flex h-full flex-col items-center justify-center p-8 text-center text-[var(--ss-workspace-muted)]">
       <GitCommit size={48} className="mb-4 text-[var(--ss-workspace-border-strong)]" />
       <p>{t('components.comparisonView.selectCompareNode')}</p>
       <p className="text-xs mt-2">{t('components.comparisonView.selectCompareNodeHint')}</p>
   </div>;

   const firstLeftEvent = leftEvents[0] || null;
   const firstRightEvent = rightEvents[0] || null;

   return (
      <div className="ss-workspace__panel ss-workspace__panel--stage flex h-full flex-col overflow-hidden">
         <div className="ss-logviewer__toolbar flex shrink-0 flex-col gap-4 px-6 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
               <div>
                  <div className="flex items-center gap-2 text-sm font-bold text-[var(--ss-workspace-heading)]">
                     <GitCompareArrows size={17} />
                     {t('components.comparisonView.activeTitle')}
                  </div>
                  <p className="mt-1 text-xs text-[var(--ss-workspace-muted)]">
                     {t('components.comparisonView.activeHint')}
                  </p>
               </div>
               <label className="flex items-center gap-2 rounded-full border border-[var(--ss-workspace-border)] bg-[var(--ss-workspace-surface-strong)] px-3 py-2 text-xs text-[var(--ss-workspace-muted)]">
                  <input type="checkbox" checked={comparisonUseLLM} onChange={(e) => setComparisonUseLLM(e.target.checked)} />
                  {t('components.comparisonView.useLLMForSummary')}
               </label>
            </div>

            <div className="grid gap-3 md:grid-cols-[1fr_auto_1fr]">
               <div className="rounded-xl border border-[color-mix(in_srgb,var(--ss-info)_28%,var(--ss-workspace-border))] bg-[color-mix(in_srgb,var(--ss-info)_10%,var(--ss-workspace-surface-strong))] p-4">
                  <div className="text-[10px] font-bold uppercase text-[color-mix(in_srgb,var(--ss-info)_70%,var(--ss-workspace-heading))]">{t('components.comparisonView.baseline')}</div>
                  <div className="mt-1 font-bold text-[var(--ss-workspace-heading)]">{nodeA.name}</div>
                  <div className="mt-1 font-mono text-xs text-[var(--ss-workspace-muted)]">{nodeA.display_id || nodeA.id}</div>
               </div>
               <div className="hidden items-center justify-center text-[var(--ss-workspace-muted)] md:flex">
                  <ArrowRight size={24} />
               </div>
               <div className="rounded-xl border border-[color-mix(in_srgb,var(--ss-secondary)_34%,var(--ss-workspace-border))] bg-[color-mix(in_srgb,var(--ss-secondary)_12%,var(--ss-workspace-surface-strong))] p-4">
                  <div className="text-[10px] font-bold uppercase text-[color-mix(in_srgb,var(--ss-secondary)_72%,var(--ss-workspace-heading))]">{t('components.comparisonView.compare')}</div>
                  <div className="mt-1 font-bold text-[var(--ss-workspace-heading)]">{nodeB.name}</div>
                  <div className="mt-1 font-mono text-xs text-[var(--ss-workspace-muted)]">{nodeB.display_id || nodeB.id}</div>
               </div>
            </div>
         </div>

         <div className="ss-logviewer__body space-y-5 p-6">
            <div className="grid gap-3 md:grid-cols-4">
               <div className="rounded-xl border border-[var(--ss-workspace-border)] bg-[var(--ss-workspace-surface-strong)] p-4">
                  <div className="flex items-center gap-2 text-xs font-bold text-[var(--ss-workspace-muted)]"><Activity size={14} /> {t('components.comparisonView.nodeAEvents')}</div>
                  <div className="mt-2 text-2xl font-bold text-[var(--ss-workspace-heading)]">{leftEvents.length}</div>
               </div>
               <div className="rounded-xl border border-[var(--ss-workspace-border)] bg-[var(--ss-workspace-surface-strong)] p-4">
                  <div className="flex items-center gap-2 text-xs font-bold text-[var(--ss-workspace-muted)]"><Activity size={14} /> {t('components.comparisonView.nodeBEvents')}</div>
                  <div className="mt-2 text-2xl font-bold text-[var(--ss-workspace-heading)]">{rightEvents.length}</div>
               </div>
               <div className="rounded-xl border border-[var(--ss-workspace-border)] bg-[var(--ss-workspace-surface-strong)] p-4">
                  <div className="flex items-center gap-2 text-xs font-bold text-[var(--ss-workspace-muted)]"><User size={14} /> {t('components.comparisonView.agentDiffFields')}</div>
                  <div className="mt-2 text-2xl font-bold text-[var(--ss-workspace-heading)]">{agentDiffFieldCount}</div>
               </div>
               <div className="rounded-xl border border-[var(--ss-workspace-border)] bg-[var(--ss-workspace-surface-strong)] p-4">
                  <div className="flex items-center gap-2 text-xs font-bold text-[var(--ss-workspace-muted)]"><GitCommit size={14} /> {t('components.comparisonView.eventTypes')}</div>
                  <div className="mt-2 text-2xl font-bold text-[var(--ss-workspace-heading)]">{eventTypeCount}</div>
               </div>
            </div>

            <div className="ss-logviewer__item p-5">
               <div className="mb-3 flex items-center gap-2 font-bold text-[color-mix(in_srgb,var(--ss-secondary)_68%,var(--ss-workspace-heading))]">
                  <Sparkles size={18} />
                  <h3>{t('components.comparisonView.smartSummary')}</h3>
               </div>
               <div className="rounded-xl border border-[var(--ss-workspace-border)] bg-[var(--ss-workspace-surface-strong)] p-4 text-sm leading-relaxed text-[var(--ss-workspace-text)]">
                  {isLoadingComparison || isGenerating ? (
                     <div className="flex items-center gap-2 text-[var(--ss-workspace-muted)]">
                        <Loader2 size={16} className="animate-spin" />
                        {t('components.comparisonView.analyzingDifferences')}
                     </div>
                  ) : compareData ? (
                     <div className="space-y-2">
                        <p className="font-medium text-[var(--ss-workspace-heading)]">{localSummary}</p>
                        <p className="text-xs text-[var(--ss-workspace-muted)]">{compareData.summary}</p>
                     </div>
                  ) : (
                     <button
                        onClick={() => setFetchTrigger(prev => prev + 1)}
                        disabled={isLoadingComparison}
                        className="text-xs text-[var(--ss-workspace-link)] hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
                     >
                        {isLoadingComparison ? (
                           <span className="inline-flex items-center gap-1.5">
                              <Loader2 size={12} className="animate-spin" />
                              {t('components.comparisonView.analyzingDifferences')}
                           </span>
                        ) : (
                           t('components.comparisonView.generateAnalysisReport')
                        )}
                     </button>
                  )}
               </div>
            </div>

            <div className="ss-logviewer__item p-5">
               <div className="mb-4 flex items-center justify-between gap-3">
                  <h3 className="text-sm font-bold text-[var(--ss-workspace-heading)]">{t('components.comparisonView.keyDivergence')}</h3>
                  <span className="text-xs text-[var(--ss-workspace-muted)]">{t('components.comparisonView.keyDivergenceHint')}</span>
               </div>
               <div className="grid gap-3 md:grid-cols-[1fr_auto_1fr]">
                  <div className="rounded-xl border border-[color-mix(in_srgb,var(--ss-info)_25%,var(--ss-workspace-border))] bg-[var(--ss-workspace-surface-strong)] p-4">
                     <div className="text-[10px] font-bold uppercase text-[var(--ss-workspace-muted)]">{t('components.comparisonView.exampleA')}</div>
                     {firstLeftEvent ? (
                        <div className="mt-2">
                           <div className="font-mono text-xs text-[color-mix(in_srgb,var(--ss-info)_70%,var(--ss-workspace-heading))]">{translateEventType(firstLeftEvent)}</div>
                           <p className="mt-2 text-sm leading-6 text-[var(--ss-workspace-text)]">{eventMainText(firstLeftEvent)}</p>
                        </div>
                     ) : (
                        <div className="mt-2 text-sm text-[var(--ss-workspace-muted)]">{t('components.comparisonView.noUniqueEvents')}</div>
                     )}
                  </div>
                  <div className="hidden items-center justify-center text-[var(--ss-workspace-muted)] md:flex">
                     <ArrowRight size={22} />
                  </div>
                  <div className="rounded-xl border border-[color-mix(in_srgb,var(--ss-secondary)_32%,var(--ss-workspace-border))] bg-[var(--ss-workspace-surface-strong)] p-4">
                     <div className="text-[10px] font-bold uppercase text-[var(--ss-workspace-muted)]">{t('components.comparisonView.exampleB')}</div>
                     {firstRightEvent ? (
                        <div className="mt-2">
                           <div className="font-mono text-xs text-[color-mix(in_srgb,var(--ss-secondary)_76%,var(--ss-workspace-heading))]">{translateEventType(firstRightEvent)}</div>
                           <p className="mt-2 text-sm leading-6 text-[var(--ss-workspace-text)]">{eventMainText(firstRightEvent)}</p>
                        </div>
                     ) : (
                        <div className="mt-2 text-sm text-[var(--ss-workspace-muted)]">{t('components.comparisonView.noUniqueEvents')}</div>
                     )}
                  </div>
               </div>
            </div>

            <div className="grid gap-4 xl:grid-cols-[1fr_0.8fr_1fr]">
               <div className="ss-logviewer__item p-4">
                  <h4 className="mb-2 text-xs font-bold text-[var(--ss-workspace-muted)]">{t('components.comparisonView.nodeAEvents')} ({leftEvents.length})</h4>
                  <div className="space-y-2 max-h-72 overflow-auto p-1">
                     {leftEvents.length === 0 ? <div className="text-xs text-[var(--ss-workspace-muted)]">{t('components.comparisonView.noUniqueEvents')}</div> : null}
                     {leftEvents.map((ev:any, idx:number) => (
                        <div key={idx} className="rounded-xl border border-[var(--ss-workspace-border)] bg-[var(--ss-workspace-surface-strong)] p-3 text-[12px]">
                           <div className="font-mono text-xs text-[var(--ss-workspace-muted)]">{translateEventType(ev)}</div>
                           <div className="mt-1 leading-5 text-[var(--ss-workspace-text)]">{eventMainText(ev)}</div>
                        </div>
                     ))}
                  </div>
               </div>

               <div className="ss-logviewer__item p-4">
                  <h4 className="mb-2 text-xs font-bold text-[var(--ss-workspace-muted)]">{t('components.comparisonView.agentDiffs')}</h4>
                  <div className="space-y-2 max-h-72 overflow-auto text-sm p-1">
                     {Object.keys(agentDiffs).length === 0 && <div className="text-[var(--ss-workspace-muted)]">{t('components.comparisonView.noAgentDiffs')}</div>}
                     {Object.entries(agentDiffs).map(([name, diffs]: any) => (
                        <div key={name} className="rounded-xl border border-[var(--ss-workspace-border)] bg-[var(--ss-workspace-surface-strong)] p-3">
                           <div className="font-medium text-[var(--ss-workspace-heading)]">{name}</div>
                           <div className="mt-1 text-[12px] text-[var(--ss-workspace-muted)]">
                              {Object.entries(diffs as object).map(([k,v]:any) => (
                                 <div key={k}>{k}: A={stringifyValue((v as any).a, 80)} → B={stringifyValue((v as any).b, 80)}</div>
                              ))}
                           </div>
                        </div>
                     ))}
                  </div>
               </div>

               <div className="ss-logviewer__item p-4">
                  <h4 className="mb-2 text-xs font-bold text-[var(--ss-workspace-muted)]">{t('components.comparisonView.nodeBEvents')} ({rightEvents.length})</h4>
                  <div className="space-y-2 max-h-72 overflow-auto p-1">
                     {rightEvents.length === 0 ? <div className="text-xs text-[var(--ss-workspace-muted)]">{t('components.comparisonView.noUniqueEvents')}</div> : null}
                     {rightEvents.map((ev:any, idx:number) => (
                        <div key={idx} className="rounded-xl border border-[var(--ss-workspace-border)] bg-[var(--ss-workspace-surface-strong)] p-3 text-[12px]">
                           <div className="font-mono text-xs text-[var(--ss-workspace-muted)]">{translateEventType(ev)}</div>
                           <div className="mt-1 leading-5 text-[var(--ss-workspace-text)]">{eventMainText(ev)}</div>
                        </div>
                     ))}
                  </div>
               </div>
            </div>

            <div className="ss-logviewer__footer px-5 py-2 text-center text-[10px]">
               * {t('components.comparisonView.dataSourceNote')}
            </div>
         </div>
      </div>
   );
};
