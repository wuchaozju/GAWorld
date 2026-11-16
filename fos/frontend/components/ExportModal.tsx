
import React, { useState } from 'react';
import { useSimulationStore } from '../store';
import { useAuthStore } from '../store/auth';
import { useTranslation } from 'react-i18next';
import { X, Download, FileJson, FileSpreadsheet, Database, Users } from 'lucide-react';
import Papa from 'papaparse';
import { mapBackendEventsToLogs } from '../store';

export const ExportModal: React.FC = () => {
  const { t } = useTranslation();
  const isOpen = useSimulationStore(state => state.isExportOpen);
  const toggle = useSimulationStore(state => state.toggleExport);
  const logs = useSimulationStore(state => state.logs);
  const rawEvents = useSimulationStore(state => state.rawEvents);
  const agents = useSimulationStore(state => state.agents);
  const currentSim = useSimulationStore(state => state.currentSimulation);
  const nodes = useSimulationStore(state => state.nodes);
  const selectedNodeId = useSimulationStore(state => state.selectedNodeId);
  const engineConfig = useSimulationStore(state => state.engineConfig);
  const llmProviders = useSimulationStore(state => state.llmProviders);

  const [format, setFormat] = useState<'json' | 'csv'>('json');
  const [scope, setScope] = useState<'all_logs' | 'agent_data'>('all_logs');
  const [isExporting, setIsExporting] = useState(false);

  if (!isOpen) return null;

  const handleExport = async () => {
    setIsExporting(true);

    try {
      // With all_logs scope, use backend export endpoint
      if (scope === 'all_logs' && currentSim?.id) {
        // Use token with fallback to auth store (same pattern as httpGet in client.ts)
        const token = (engineConfig as any).token ?? useAuthStore.getState().accessToken ?? undefined;
        const baseUrl = engineConfig.endpoint;
        const simId = currentSim.id;

        const response = await fetch(
          `${baseUrl}/simulations/${simId}/export?format=${format}`,
          {
            headers: {
              'Authorization': `Bearer ${token}`
            }
          }
        );

        if (!response.ok) {
          throw new Error(`Export failed: ${response.status}`);
        }

        // Get filename from Content-Disposition header
        const contentDisp = response.headers.get('Content-Disposition');
        const filenameMatch = contentDisp?.match(/filename="(.+)"/);
        const filename = filenameMatch ? filenameMatch[1] : `export.${format}`;

        // Download file
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
      } else {
        // agent_data scope: use local export
        await handleLocalExport();
      }
    } catch (error) {
      console.error('Export error:', error);
      alert(t('components.exportModal.exportFailed') || 'Export failed. Please try again.');
    } finally {
      setIsExporting(false);
      toggle(false);
    }
  };

  const handleLocalExport = async () => {
    let content = '';
    let mimeType = 'application/json';
    let filename = `${currentSim?.name || 'simulation'}_${scope}_${new Date().toISOString().slice(0,10)}`;

    // 1. Prepare Data
    let dataToExport: any[] | object = [];

    if (scope === 'all_logs') {
      // Export uses raw events re-mapped, including all metadata events
      if (rawEvents.length > 0) {
        // Group events by node (if events include node information)
        // Otherwise use selected node's information as default
        const currentNode = nodes.find(n => n.id === selectedNodeId);
        const defaultNodeId = currentNode?.id || selectedNodeId || 'unknown';
        const defaultRound = currentNode?.depth || 0;

        // Re-map all events, including all metadata
        // Note: If event contains node information, extract from event
        const allLogs = mapBackendEventsToLogs(
          rawEvents,
          defaultNodeId,
          defaultRound,
          agents,
          true // Include all metadata when exporting
        );
        dataToExport = allLogs.map(l => ({ ...l, image_preview: l.imageUrl ? `![img](${l.imageUrl})` : '' }));
      } else {
        // If no raw events, use current filtered logs
        dataToExport = logs.map(l => ({ ...l, image_preview: l.imageUrl ? `![img](${l.imageUrl})` : '' }));
      }
    } else {
      dataToExport = agents;
    }

    // 2. Format Data
    if (format === 'json') {
      content = JSON.stringify(dataToExport, null, 2);
      mimeType = 'application/json';
      filename += '.json';
    } else {
      // CSV
      if (scope === 'all_logs') {
        const flat = (dataToExport as any[]).map(l => ({
          timestamp: (l as any).timestamp,
          nodeId: (l as any).nodeId,
          type: (l as any).type,
          agentId: (l as any).agentId,
          content: (l as any).content,
          imageUrl: (l as any).imageUrl,
          image_preview: (l as any).image_preview,
        }));
        content = Papa.unparse(flat);
      } else {
        // For agents, create a clean export with flattened properties
        // First, collect all unique property keys across all agents
        const allPropertyKeys = new Set<string>();
        agents.forEach(a => {
          if (a.properties && typeof a.properties === 'object') {
            Object.keys(a.properties).forEach(key => allPropertyKeys.add(key));
          }
        });

        // Extract short role name from "You are a [Role]." pattern
        const extractRoleName = (roleText: string) => {
          if (!roleText) return '';
          // Match "You are a/an [Role Name]." at the start
          const match = roleText.match(/^You are (?:a|an) ([^.]+)\./i);
          if (match) {
            return match[1].trim(); // Return just the role name
          }
          // If pattern doesn't match, return as-is (might already be short)
          return roleText.split('.')[0].trim();
        };

        // Clean profile text by removing "You are a X." prefix
        const cleanProfile = (profile: string) => {
          if (!profile) return '';
          // Remove "You are a [Role]." pattern from the beginning
          return profile.replace(/^You are a [^.]+\.\s*/i, '').trim();
        };

        // Build flattened agent data with dynamic property columns
        const flattenedAgents = agents.map(a => {
          // Try to get LLM info from llmConfig first, then from properties.provider_id
          let llmModel = 'unknown';
          let llmProvider = 'unknown';

          // Sentinel values ("backend"/"default") mean the frontend couldn't resolve
          // the provider at creation time — skip to provider_id lookup instead.
          const isSentinelLlmConfig =
            a.llmConfig &&
            (a.llmConfig.provider === 'backend' || a.llmConfig.model === 'default');

          if (a.llmConfig && a.llmConfig.model && !isSentinelLlmConfig) {
            llmModel = a.llmConfig.model;
            llmProvider = a.llmConfig.provider || 'unknown';
          } else {
            // Resolve actual provider via provider_id (from stratified distribution)
            const providerId = a.provider_id ?? a.properties?.provider_id;
            if (providerId != null) {
              const providers = useSimulationStore.getState().llmProviders || [];
              const provider = providers.find((p: any) => p.id === Number(providerId));
              if (provider) {
                llmProvider = provider.provider || provider.name;
                llmModel = provider.model || 'unknown';
              }
            }
          }

          const baseData: any = {
            id: a.id,
            name: a.name,
            role: extractRoleName(a.role || ''),
            profile: cleanProfile(a.profile || ''),
            llm_provider: llmProvider,
            llm_model: llmModel
          };

          // Add flattened properties (exclude internal/redundant fields)
          const excludeKeys = new Set(['provider_id', 'demographic_attributes', 'role']);
          allPropertyKeys.forEach(key => {
            if (!excludeKeys.has(key)) {
              baseData[key] = a.properties?.[key] ?? '';
            }
          });

          return baseData;
        });

        content = Papa.unparse(flattenedAgents);
      }
      mimeType = 'text/csv';
      filename += '.csv';
    }

    // 3. Trigger Download
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="ss-extension-modal">
      <div className="ss-extension-modal__panel ss-extension-modal__panel--compact animate-in zoom-in-95 duration-200">
        <div className="ss-extension-modal__header">
          <div className="ss-extension-modal__header-title">
            <div className="ss-extension-modal__header-icon">
              <Download size={18} />
            </div>
            <div className="ss-extension-modal__header-copy">
              <h2>{t('components.exportModal.title')}</h2>
            </div>
          </div>
          <button onClick={() => toggle(false)} className="text-slate-400 hover:text-slate-600">
            <X size={20} />
          </button>
        </div>

        <div className="ss-extension-modal__body space-y-6">
          {/* Scope Selection */}
          <div>
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-3">
              {t('components.exportModal.selectContent')}
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setScope('all_logs')}
                className={`p-3 border rounded-lg flex flex-col items-center gap-2 transition-all ${scope === 'all_logs' ? 'bg-amber-50 border-amber-400 text-amber-800' : 'hover:bg-amber-50/40 border-slate-200 text-slate-600'}`}
              >
                <Database size={24} className={scope === 'all_logs' ? 'text-amber-600' : 'text-slate-400'} />
                <span className="text-sm font-medium">{t('components.exportModal.allLogs')}</span>
              </button>
              <button
                onClick={() => setScope('agent_data')}
                className={`p-3 border rounded-lg flex flex-col items-center gap-2 transition-all ${scope === 'agent_data' ? 'bg-amber-50 border-amber-400 text-amber-800' : 'hover:bg-amber-50/40 border-slate-200 text-slate-600'}`}
              >
                <Users size={24} className={scope === 'agent_data' ? 'text-amber-600' : 'text-slate-400'} />
                <span className="text-sm font-medium">{t('components.exportModal.agentData')}</span>
              </button>
            </div>
          </div>

          {/* Format Selection */}
          <div>
            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-3">
              {t('components.exportModal.selectFormat')}
            </label>
            <div className="flex gap-4">
              <button
                onClick={() => setFormat('json')}
                className={`flex-1 py-2 px-4 rounded border flex items-center justify-center gap-2 text-sm font-medium transition-all ${format === 'json' ? 'bg-amber-600 text-white border-amber-600 shadow-md' : 'bg-white text-slate-600 hover:bg-amber-50/40'}`}
              >
                <FileJson size={16} /> {t('components.exportModal.json')}
              </button>
              <button
                onClick={() => setFormat('csv')}
                className={`flex-1 py-2 px-4 rounded border flex items-center justify-center gap-2 text-sm font-medium transition-all ${format === 'csv' ? 'bg-amber-600 text-white border-amber-600 shadow-md' : 'bg-white text-slate-600 hover:bg-amber-50/40'}`}
              >
                <FileSpreadsheet size={16} /> {t('components.exportModal.excelCsv')}
              </button>
            </div>
          </div>

          <div className="bg-amber-50/70 p-3 rounded text-xs text-slate-600 flex gap-2 items-start border border-amber-200/70">
            <div className="shrink-0 mt-0.5 text-amber-600">ℹ️</div>
            <p>
              {scope === 'all_logs' && format === 'csv' && t('components.exportModal.hintAllLogsCsv')}
              {scope === 'all_logs' && format === 'json' && t('components.exportModal.hintAllLogsJson')}
              {scope === 'agent_data' && format === 'csv' && t('components.exportModal.hintAgentDataCsv')}
              {scope === 'agent_data' && format === 'json' && t('components.exportModal.hintAgentDataJson')}
            </p>
          </div>
        </div>

        <div className="ss-extension-modal__footer">
          <button onClick={() => toggle(false)} className="ss-extension-modal__action">
            {t('components.exportModal.cancel')}
          </button>
          <button
            onClick={handleExport}
            disabled={isExporting}
            className="ss-extension-modal__action ss-extension-modal__action--primary disabled:opacity-70 disabled:cursor-wait"
          >
            {isExporting ? t('components.exportModal.generating') : t('components.exportModal.confirmExport')}
            {!isExporting && <Download size={16} />}
          </button>
        </div>
      </div>
    </div>
  );
};
