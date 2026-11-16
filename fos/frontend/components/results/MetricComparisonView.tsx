import React, { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useSimulationStore } from '@/store';
import { useAuthStore } from '@/store/auth';
import { getSimEvents } from '@/services/simulationTree';
import { mapBackendEventsToLogs } from '@/store/helpers';
import { listMetrics, computeMetricTrajectories, computeMetricAggregate, hydrateAgentHistoryFromLogs } from '@/utils/resultsComputations';
import type { VariantAggregate } from '@/utils/resultsComputations';
import { AggregateTrajectoryChart } from './AggregateTrajectoryChart';
import { MetricTrajectoryChart } from './MetricTrajectoryChart';
import { AiSummarySection } from './AiSummarySection';
import { ExportSection } from './ExportSection';

const L = (zh: string, en: string, locale: string) => locale === 'zh' ? zh : en;

export function MetricComparisonView({ language = 'en' }: { language?: 'en' | 'zh' }) {
  const { t: i18nT } = useTranslation();
  const agents = useSimulationStore((s: any) => s.agents);
  const logs = useSimulationStore((s: any) => s.logs);
  const nodes = useSimulationStore((s: any) => s.nodes);
  const selectedNodeId = useSimulationStore((s: any) => s.selectedNodeId);
  const compareTargetNodeId = useSimulationStore((s: any) => s.compareTargetNodeId);
  const currentSimulation = useSimulationStore((s: any) => s.currentSimulation);
  const engineConfig = useSimulationStore((s: any) => s.engineConfig);

  const [selectedMetric, setSelectedMetric] = useState<string>('');
  const [variantData, setVariantData] = useState<VariantAggregate[]>([]);
  const [perAgentSeries, setPerAgentSeries] = useState<Record<string, any[]>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string>('');
  const [viewMode, setViewMode] = useState<'per-agent' | 'aggregate'>('aggregate');

  // AI Analysis state (comparison-specific)
  const comparisonSummary = useSimulationStore((s: any) => s.comparisonSummary);
  const isGeneratingComparison = useSimulationStore((s: any) => s.isGenerating);
  const generateComparisonAnalysis = useSimulationStore((s: any) => s.generateComparisonAnalysis);

  // Resolve node names
  const nodeALabel = useMemo(() => {
    const n = (nodes || []).find((x: any) => x.id === selectedNodeId);
    return n?.meta?.variant_name || n?.name || selectedNodeId || '';
  }, [nodes, selectedNodeId]);
  const nodeBLabel = useMemo(() => {
    const n = (nodes || []).find((x: any) => x.id === compareTargetNodeId);
    return n?.meta?.variant_name || n?.name || compareTargetNodeId || '';
  }, [nodes, compareTargetNodeId]);

  // Fetch and compute comparison data when both nodes are selected
  useEffect(() => {
    if (!selectedNodeId || !compareTargetNodeId || selectedNodeId === compareTargetNodeId) {
      setVariantData([]);
      setError('');
      return;
    }

    if (!currentSimulation?.id || !engineConfig?.endpoint) return;

    const simId = currentSimulation.id;
    const baseUrl = engineConfig.endpoint;
    const token = (engineConfig as any).token ?? useAuthStore.getState().accessToken ?? undefined;
    const nodeIds = [selectedNodeId, compareTargetNodeId];

    setIsLoading(true);
    setError('');

    (async () => {
      try {
        const results = await Promise.all(
          nodeIds.map(async (nid) => {
            const nodeNum = Number(nid);
            if (!Number.isFinite(nodeNum)) return null;
            const rawEvents = await getSimEvents(baseUrl, simId, nodeNum, token).catch(() => []);
            const nodeEvents = mapBackendEventsToLogs(rawEvents, String(nodeNum), 0, agents, false);
            const hydrated = hydrateAgentHistoryFromLogs(nodeEvents, agents);
            const node = (nodes || []).find((x: any) => x.id === nid);
            const name = node?.meta?.variant_name || node?.name || `Node ${nid}`;
            return { name, hydrated };
          })
        );

        const valid = results.filter(Boolean) as { name: string; hydrated: any[] }[];
        if (valid.length < 2) {
          setError(L('无法获取节点数据。', 'Failed to fetch node data.', language));
          return;
        }

        const firstMetrics = listMetrics(valid[0].hydrated);
        const secondMetrics = listMetrics(valid[1].hydrated);
        const commonMetrics = firstMetrics.filter((m) => secondMetrics.includes(m));

        if (commonMetrics.length === 0) {
          setError(L('所选节点没有共同的指标数据，可能尚未推进。', 'No common metrics between selected nodes. Try advancing first.', language));
          return;
        }

        const metric = commonMetrics.includes(selectedMetric) ? selectedMetric : commonMetrics[0];
        setSelectedMetric(metric);

        const seriesByVariant: Record<string, any[]> = {};
        for (const r of valid) {
          try {
            seriesByVariant[r.name] = computeMetricTrajectories(r.hydrated, metric);
          } catch { seriesByVariant[r.name] = []; }
        }

        setPerAgentSeries(seriesByVariant);

        const aggregates = Object.entries(seriesByVariant)
          .filter(([, s]) => s.length > 0)
          .map(([name, series]) => ({ variantName: name, points: computeMetricAggregate(series) }));

        if (aggregates.length < 2) {
          setError(L('有指标数据但不足以计算轨迹。', 'Metric data exists but insufficient for trajectories.', language));
          return;
        }

        setVariantData(aggregates);
      } catch (e) {
        console.warn('Metric comparison failed:', e);
        setError(L('对比加载失败。', 'Comparison failed to load.', language));
      } finally {
        setIsLoading(false);
      }
    })();
  }, [selectedNodeId, compareTargetNodeId, currentSimulation?.id, engineConfig?.endpoint]);

  const allMetrics = useMemo(() => {
    const h = hydrateAgentHistoryFromLogs(logs || [], agents);
    return listMetrics(h);
  }, [logs, agents]);

  const onGenerate = () => {
    generateComparisonAnalysis();
  };

  const bothNodesSelected = selectedNodeId && compareTargetNodeId && selectedNodeId !== compareTargetNodeId;

  return (
    <div className="p-5 space-y-4">
      {/* Guidance / status */}
      {!bothNodesSelected ? (
        <div className="rounded-lg border p-4 text-sm text-center"
          style={{ background: 'var(--ss-surface-inset)', borderColor: 'var(--ss-border)', color: 'var(--ss-text-muted)' }}>
          {L(
            '切换到工作台，左键点击选择主节点，按住 Alt 再点击另一个节点设为对比对象。然后回到此处查看对比。',
            'Go to Workspace, click to select the first node, then Alt+click a second node as comparison target. Come back here to see the comparison.',
            language
          )}
        </div>
      ) : (
        <div className="flex items-center justify-center gap-4 text-sm font-medium"
          style={{ color: 'var(--ss-heading)' }}>
          <span className="px-3 py-1 rounded" style={{ background: 'var(--ss-brand-soft)', color: 'var(--ss-brand-primary)' }}>
            {nodeALabel}
          </span>
          <span style={{ color: 'var(--ss-text-muted)' }}>vs</span>
          <span className="px-3 py-1 rounded" style={{ background: 'var(--ss-accent-warm-soft)', color: 'var(--ss-accent-warm)' }}>
            {nodeBLabel}
          </span>
        </div>
      )}

      {/* Metric selector (shown only when comparing) */}
      {bothNodesSelected && allMetrics.length > 0 ? (
        <div className="flex gap-2 items-center">
          <label className="text-xs font-medium" style={{ color: 'var(--ss-heading)' }}>
            {L('指标', 'Metric', language)}:
          </label>
          <select value={selectedMetric} onChange={(e) => setSelectedMetric(e.target.value)}
            className="text-sm border rounded px-2 py-1"
            style={{ background: 'var(--ss-input-bg)', borderColor: 'var(--ss-border)', color: 'var(--ss-text)' }}>
            {allMetrics.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
      ) : null}

      {/* Error */}
      {error ? (
        <div className="text-sm py-4" style={{ color: 'var(--ss-text-muted)' }}>
          {error}
        </div>
      ) : null}

      {/* AI Analysis */}
      <div className="rounded-lg border p-4"
        style={{ background: 'var(--ss-workspace-surface)', borderColor: 'var(--ss-workspace-border)' }}>
        <div className="text-xs font-semibold uppercase mb-3"
          style={{ color: 'var(--ss-workspace-muted)', letterSpacing: '0.05em' }}>
          AI Analysis
        </div>
        <AiSummarySection
          summary={comparisonSummary}
          isGenerating={isGeneratingComparison}
          error={null}
          onGenerate={onGenerate}
          labels={{ generate: i18nT('results.generate'), generating: i18nT('results.generating') }}
        />
      </div>

      {/* Metric chart */}
      <div className="rounded-lg border p-4"
        style={{ background: 'var(--ss-workspace-surface)', borderColor: 'var(--ss-workspace-border)' }}>
        <div className="text-xs font-semibold uppercase mb-3"
          style={{ color: 'var(--ss-workspace-muted)', letterSpacing: '0.05em' }}>
          {L('指标对比', 'Metric Comparison', language)}
        </div>
        {variantData.length >= 2 && (
          <div style={{ display: 'flex', gap: '4px', marginBottom: '8px' }}>
            {(['per-agent', 'aggregate'] as const).map((mode) => (
              <button key={mode} type="button" onClick={() => setViewMode(mode)}
                style={{
                  padding: '2px 8px', fontSize: '11px', borderRadius: '4px', cursor: 'pointer',
                  border: '1px solid var(--ss-workspace-border)',
                  background: viewMode === mode ? 'var(--ss-brand-soft)' : 'transparent',
                  color: viewMode === mode ? 'var(--ss-brand-primary)' : 'var(--ss-workspace-muted)',
                }}>
                {mode === 'per-agent' ? L('个体', 'Per-agent', language) : L('汇总', 'Aggregate', language)}
              </button>
            ))}
          </div>
        )}
        {isLoading ? (
          <div className="text-sm py-8 text-center" style={{ color: 'var(--ss-text-muted)' }}>
            {L('加载中...', 'Loading...', language)}
          </div>
        ) : variantData.length >= 2 && viewMode === 'aggregate' ? (
          <AggregateTrajectoryChart
            variants={variantData}
            metric={selectedMetric || allMetrics[0] || ''}
            width={700}
            height={300}
            xLabel={L('步数', 'Step', language)}
            yLabel={selectedMetric || allMetrics[0] || ''}
            meanLabel={L('均值', 'Mean', language)}
            rangeLabel={L('范围', 'Range', language)}
          />
        ) : viewMode === 'per-agent' && Object.keys(perAgentSeries).length >= 2 ? (
          <div className="space-y-6">
            {Object.entries(perAgentSeries).map(([name, series]) => (
              <div key={name}>
                <div className="text-xs font-semibold mb-1" style={{ color: 'var(--ss-heading)' }}>{name}</div>
                <MetricTrajectoryChart series={series} metric={selectedMetric || allMetrics[0] || ''} width={700} height={200} />
              </div>
            ))}
          </div>
        ) : bothNodesSelected && !error ? (
          <div className="text-sm py-8 text-center" style={{ color: 'var(--ss-text-muted)' }}>
            {L('所选节点没有指标数据，请先推进仿真。', 'No metric data for selected nodes. Advance the simulation first.', language)}
          </div>
        ) : null}
      </div>

      {/* Export */}
      <div className="rounded-lg border p-4"
        style={{ background: 'var(--ss-workspace-surface)', borderColor: 'var(--ss-workspace-border)' }}>
        <div className="text-xs font-semibold uppercase mb-3"
          style={{ color: 'var(--ss-workspace-muted)', letterSpacing: '0.05em' }}>
          Export
        </div>
        <ExportSection
          onExportCsv={async () => {
            const token = (engineConfig as any).token ?? useAuthStore.getState().accessToken ?? undefined;
            const baseUrl = engineConfig.endpoint;
            const response = await fetch(
              `${baseUrl}/simulations/${currentSimulation?.id}/export?format=csv`,
              { headers: { 'Authorization': `Bearer ${token}` } }
            );
            if (!response.ok) throw new Error(`Export failed: ${response.status}`);
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'comparison_export.csv';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
          }}
          onExportMarkdown={() => {}}
          labels={{ csv: i18nT('results.exportCsv'), markdown: i18nT('results.exportReport') }}
        />
      </div>
    </div>
  );
}
