/**
 * Main simulation workspace page.
 *
 * Loads one simulation and shows the main work areas people switch between:
 * workspace, agents, intervention, and analysis.
 *
 * Exports: SimulationPage (default), SimulationPage (named)
 */

import React from "react";
import { SimTree } from "../components/SimTree";
import { Sidebar } from "../components/Sidebar";
import { LogViewer } from "../components/LogViewer";
import { SyncModal } from "../components/SyncModal";
import { ToastContainer } from "../components/Toast";
import { useSimulationStore } from "../store";
import { useNavigate, useParams } from "react-router-dom";
import { getSimulation as apiGetSimulation } from "../services/simulations";
import { getTreeGraph, getSimEvents, getSimState, getRehydrate } from "../services/simulationTree";
import { useAuthStore } from "../store/auth";
import { useTranslation } from "react-i18next";
import { useShallow } from "zustand/react/shallow";
import { TabRail } from "../components/TabRail";
import { PeekOverlay } from "../components/PeekOverlay";
import { RouteLoading } from "../components/RouteLoading";
import { getWorkspaceOverlayMountState } from "./simulationPageRender";
import "../styles/routes/workspace.css";

const ComparisonView = React.lazy(() =>
  import("../components/ComparisonView").then((module) => ({ default: module.ComparisonView }))
);
const ExperimentBuilderModal = React.lazy(() =>
  import("../components/ExperimentBuilderModal").then((module) => ({ default: module.ExperimentBuilderModal }))
);
const HelpModal = React.lazy(() =>
  import("../components/HelpModal").then((module) => ({ default: module.HelpModal }))
);
const AnalyticsPanel = React.lazy(() =>
  import("../components/AnalyticsPanel").then((module) => ({ default: module.AnalyticsPanel }))
);
const AnalyseTab = React.lazy(() =>
  import("../components/AnalyseTab").then((module) => ({ default: module.AnalyseTab }))
);
const ExportModal = React.lazy(() =>
  import("../components/ExportModal").then((module) => ({ default: module.ExportModal }))
);
const ExperimentDesignModal = React.lazy(() =>
  import("../components/ExperimentDesignModal").then((module) => ({ default: module.ExperimentDesignModal }))
);
const TimeSettingsModal = React.lazy(() =>
  import("../components/TimeSettingsModal").then((module) => ({ default: module.TimeSettingsModal }))
);
const TemplateSaveModal = React.lazy(() =>
  import("../components/TemplateSaveModal").then((module) => ({ default: module.TemplateSaveModal }))
);
const NetworkEditorModal = React.lazy(() =>
  import("../components/NetworkEditorModal").then((module) => ({ default: module.NetworkEditorModal }))
);
const ReportModal = React.lazy(() =>
  import("../components/ReportModal").then((module) => ({ default: module.ReportModal }))
);
const GlobalKnowledgePanel = React.lazy(() =>
  import("../components/GlobalKnowledgePanel").then((module) => ({ default: module.GlobalKnowledgePanel }))
);
const GuideAssistant = React.lazy(() =>
  import("../components/GuideAssistant").then((module) => ({ default: module.GuideAssistant }))
);
const InterventionTab = React.lazy(() =>
  import("../components/InterventionTab").then((module) => ({ default: module.InterventionTab }))
);

// ---------------- SimulationPage ----------------

const SimulationPage: React.FC = () => {
  const { t } = useTranslation();
  const isCompareMode = useSimulationStore((state) => state.isCompareMode);
  const [railWidth, setRailWidth] = React.useState(96);
  const isResizingRailRef = React.useRef(false);
  const params = useParams();
  const navigate = useNavigate();
  const simIdParam = params['id'] || params['simulationId'] || null;
  const engineConfig = useSimulationStore((state) => state.engineConfig);
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const hasRestored = useAuthStore((s) => s.hasRestored);
  const workspaceOverlayState = useSimulationStore(useShallow((state) => ({
      isWizardOpen: state.isWizardOpen,
      isHelpModalOpen: state.isHelpModalOpen,
      isAnalyticsOpen: state.isAnalyticsOpen,
      isExportOpen: state.isExportOpen,
      isExperimentDesignerOpen: state.isExperimentDesignerOpen,
      isTimeSettingsOpen: state.isTimeSettingsOpen,
      isSaveTemplateOpen: state.isSaveTemplateOpen,
      isNetworkEditorOpen: state.isNetworkEditorOpen,
      isReportModalOpen: state.isReportModalOpen,
      globalKnowledgeOpen: state.globalKnowledgeOpen,
      isGuideOpen: state.isGuideOpen,
    })));
  const workspaceOverlayMounts = getWorkspaceOverlayMountState(workspaceOverlayState);

  React.useEffect(() => {
    (async () => {
      if (!simIdParam) return;

      // Wait until auth restoration has completed
      if (!hasRestored || !isAuthenticated) return;

      await useSimulationStore.getState().loadSimulationById(String(simIdParam));
      return;
      try {
          const token = (engineConfig as any).token as string | undefined;
          let sim: any | null = null;
          try {
            sim = await apiGetSimulation(String(simIdParam));
            // Map scene_config.social_network to socialNetwork for frontend
            if (sim?.scene_config?.social_network) {
              sim.socialNetwork = sim.scene_config.social_network;
            }
          } catch (err) {
            console.warn('apiGetSimulation failed, will attempt rehydrate fallback', err);
            // try rehydrate directly using simIdParam (may succeed even if primary endpoint requires auth)
            try {
              const re = await getRehydrate(engineConfig.endpoint, String(simIdParam), token).catch(() => null);
              if (re && typeof re === 'object') {
                // construct nodes & agents from rehydrate response and set state
                const nodesRaw2 = (re.nodes || []) as any[];
                const nodes2 = nodesRaw2.map((n: any) => ({
                  id: String(n.id),
                  display_id: String(n.id),
                  parentId: n.parent == null ? null : String(n.parent),
                  name: t('simPage.nodeId', { id: n.id }),
                  depth: n.depth,
                  isLeaf: (n.depth || 0) === (Math.max(...(nodesRaw2.map((x: any) => x.depth || 0))) || 0),
                  status: 'completed',
                  timestamp: new Date().toLocaleTimeString(),
                  worldTime: new Date().toISOString(),
                  meta: n.meta || {}
                }));

                let agents2: any[] = [];
                try {
                  const firstNode = nodesRaw2.find((n: any) => Number(n.id) === Number(nodes2[0]?.id));
                  const simSnap2 = firstNode?.sim || {};
                  const latestAgents2 = simSnap2?.agents || re.agents || [];
                  if (Array.isArray(latestAgents2)) {
                    agents2 = latestAgents2.map((a: any, idx: number) => ({
                      id: `a-${idx}-${a.name}`,
                      name: a.name,
                      role: a.role || (a.properties || {}).role || '',
                      avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || String(idx))}`,
                      profile: '',
                      llmConfig: { provider: 'mock', model: 'default' },
                      properties: a.properties || {},
                      history: {},
                      memory: (a.short_memory || []).map((m: any, j: number) => ({ id: `m-${idx}-${j}`, round: Number(simSnap2?.turns || 0), content: String(m.content ?? ''), type: 'dialogue', timestamp: new Date().toISOString() })),
                      knowledgeBase: a.knowledgeBase || []
                    }));
                  } else if (latestAgents2 && typeof latestAgents2 === 'object') {
                    agents2 = Object.keys(latestAgents2).map((k: string, idx: number) => {
                      const a = (latestAgents2 as any)[k] || {};
                      return {
                        id: `a-${idx}-${a.name || k}`,
                        name: a.name || k,
                        role: a.role || (a.properties || {}).role || '',
                        avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || k)}`,
                        profile: '',
                        llmConfig: { provider: 'mock', model: 'default' },
                        properties: a.properties || {},
                        history: {},
                        memory: (a.short_memory || []).map((m: any, j: number) => ({ id: `m-${idx}-${j}`, round: Number(simSnap2?.turns || 0), content: String(m.content ?? ''), type: 'dialogue', timestamp: new Date().toISOString() })),
                        knowledgeBase: a.knowledgeBase || []
                      };
                    });
                  }
                } catch (e) {
                  console.warn('rehydrate parsing failed', e);
                }

                if (agents2 && agents2.length > 0) {
                  useSimulationStore.setState({
                    currentSimulation: { id: String(simIdParam) } as any,
                    nodes: nodes2,
                    selectedNodeId: nodes2[0]?.id ?? null,
                    agents: agents2,
                    rawEvents: []
                  } as any);
                  return;
                }
              }
            } catch (e) {
              console.warn('rehydrate fallback failed', e);
            }
            return; // give up after attempting rehydrate
          }
          if (!sim) return;

          // Prefer live graph/state/events whenever the backend is reachable
          try {
            const base = engineConfig.endpoint;
            const liveToken = (engineConfig as any).token;
            const graph = await getTreeGraph(base, sim.id, liveToken).catch(() => null);
            const rootId = graph?.root ?? null;
            const simState = rootId != null
              ? await getSimState(base, sim.id, rootId, liveToken).catch(() => null)
              : null;
            const events = rootId != null
              ? await getSimEvents(base, sim.id, rootId, liveToken).catch(() => [])
              : [];

            if (graph && simState) {
              const mapGraphToNodes = (graph: any) => {
                const parentMap = new Map<number, number | null>();
                const childrenSet = new Set<number>();
                for (const edge of (graph.edges || [])) {
                  parentMap.set(edge.to, edge.from);
                  childrenSet.add(edge.from);
                }
                const nowIso = new Date().toISOString();
                return (graph.nodes || []).map((n: any) => {
                  const pid = parentMap.has(n.id) ? parentMap.get(n.id)! : null;
                  const isLeaf = !childrenSet.has(n.id);
                  const running = new Set(graph.running || []);
                  const meta = (n as any).meta || null;
                  return {
                    id: String(n.id),
                    display_id: String(n.id),
                    parentId: pid == null ? null : String(pid),
                    name: t('simPage.nodeId', { id: n.id }),
                    depth: n.depth,
                    isLeaf,
                    status: running.has(n.id) ? 'running' : 'completed',
                    timestamp: new Date().toLocaleTimeString(),
                    worldTime: nowIso,
                    meta
                  };
                });
              };

              const nodes = mapGraphToNodes(graph);

              const agents = (simState.agents || []).map((a: any, idx: number) => ({
                id: `a-${idx}-${a.name}`,
                name: a.name,
                role: a.role || '',
                avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || String(idx))}`,
                profile: '',
                llmConfig: { provider: 'mock', model: 'default' },
                properties: {},
                history: {},
                memory: (a.short_memory || []).map((m: any, j: number) => ({ id: `m-${idx}-${j}`, round: Number(simState.turns || 0), content: String(m.content ?? ''), type: 'dialogue', timestamp: new Date().toISOString() })),
                knowledgeBase: a.knowledgeBase || []
              }));

              // Map scene_config.social_network to socialNetwork for frontend
              const socialNetwork = (sim as any).scene_config?.social_network || {};

              useSimulationStore.setState({
                currentSimulation: { ...sim, socialNetwork },
                nodes,
                selectedNodeId: rootId != null ? String(rootId) : nodes[0]?.id ?? null,
                agents: agents,
                rawEvents: events || []
              } as any);
              return;
            }
          } catch (e) {
            // fall through to latest_state fallback
            console.warn('Failed to fetch live graph/state/events, falling back to latest_state', e);
          }

          // Fallback 1: try server-side rehydrate snapshot (graph + sim)
          try {
            const re = await getRehydrate(engineConfig.endpoint, sim.id, token).catch(() => null);
            if (re && typeof re === 'object') {
              const nodesRaw2 = (re.nodes || []) as any[];
              const nodes2 = nodesRaw2.map((n: any) => ({
                id: String(n.id),
                display_id: String(n.id),
                parentId: n.parent == null ? null : String(n.parent),
                name: t('simPage.nodeId', { id: n.id }),
                depth: n.depth,
                isLeaf: (n.depth || 0) === (Math.max(...(nodesRaw2.map((x: any) => x.depth || 0))) || 0),
                status: 'completed',
                timestamp: new Date().toLocaleTimeString(),
                worldTime: new Date().toISOString(),
                meta: n.meta || {}
              }));

              let agents2: any[] = [];
              try {
                const firstNode = nodesRaw2.find((n: any) => Number(n.id) === Number(nodes2[0]?.id));
                const simSnap2 = firstNode?.sim || {};
                const latestAgents2 = simSnap2?.agents || re.agents || [];
                if (Array.isArray(latestAgents2)) {
                  agents2 = latestAgents2.map((a: any, idx: number) => ({
                    id: `a-${idx}-${a.name}`,
                    name: a.name,
                    role: a.role || (a.properties || {}).role || '',
                    avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || String(idx))}`,
                    profile: '',
                    llmConfig: { provider: 'mock', model: 'default' },
                    properties: a.properties || {},
                    history: {},
                    memory: (a.short_memory || []).map((m: any, j: number) => ({ id: `m-${idx}-${j}`, round: Number(simSnap2?.turns || 0), content: String(m.content ?? ''), type: 'dialogue', timestamp: new Date().toISOString() })),
                    knowledgeBase: a.knowledgeBase || []
                  }));
                } else if (latestAgents2 && typeof latestAgents2 === 'object') {
                  agents2 = Object.keys(latestAgents2).map((k: string, idx: number) => {
                    const a = (latestAgents2 as any)[k] || {};
                    return {
                      id: `a-${idx}-${a.name || k}`,
                      name: a.name || k,
                      role: a.role || (a.properties || {}).role || '',
                      avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || k)}`,
                      profile: '',
                      llmConfig: { provider: 'mock', model: 'default' },
                      properties: a.properties || {},
                      history: {},
                      memory: (a.short_memory || []).map((m: any, j: number) => ({ id: `m-${idx}-${j}`, round: Number(simSnap2?.turns || 0), content: String(m.content ?? ''), type: 'dialogue', timestamp: new Date().toISOString() })),
                      knowledgeBase: a.knowledgeBase || []
                    };
                  });
                }
              } catch (e) {
                console.warn('rehydrate parsing failed', e);
              }

              if (nodes2.length > 0) {
                useSimulationStore.setState({
                  currentSimulation: sim,
                  nodes: nodes2,
                  selectedNodeId: nodes2[0]?.id ?? null,
                  agents: agents2,
                  rawEvents: []
                } as any);
                return;
              }
            }
          } catch (e) {
            console.warn('rehydrate fallback failed', e);
          }

          // Fallback: if backend not connected or live fetch failed, try to use persisted latest_state
          try {
            const latest = (sim as any).latest_state;
            if (latest && typeof latest === 'object') {
              const nodesRaw = (latest.nodes || []) as any[];
              const nodes = nodesRaw.map((n: any) => ({
                id: String(n.id),
                display_id: String(n.id),
                parentId: n.parent == null ? null : String(n.parent),
                name: t('simPage.nodeId', { id: n.id }),
                depth: n.depth,
                isLeaf: (n.depth || 0) === (Math.max(...(nodesRaw.map((x: any) => x.depth || 0))) || 0),
                status: 'completed',
                timestamp: new Date().toLocaleTimeString(),
                worldTime: new Date().toISOString(),
                meta: n.meta || {}
              }));

              // extract agents from the node sim snapshot if present
              let agents: any[] = [];
              if (Array.isArray(nodesRaw)) {
                const matched = nodesRaw.find((n: any) => Number(n.id) === Number(nodes[0]?.id));
                const simSnap = matched?.sim || {};
                const latestAgents = simSnap?.agents || latest.agents || [];
                if (latestAgents && typeof latestAgents === 'object') {
                  if (Array.isArray(latestAgents)) {
                    agents = latestAgents.map((a: any, idx: number) => ({
                      id: `a-${idx}-${a.name}`,
                      name: a.name,
                      role: a.role || (a.properties || {}).role || '',
                      avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || String(idx))}`,
                      profile: '',
                      llmConfig: { provider: 'mock', model: 'default' },
                      properties: a.properties || {},
                      history: {},
                      memory: (a.short_memory || []).map((m: any, j: number) => ({ id: `m-${idx}-${j}`, round: Number(simSnap?.turns || 0), content: String(m.content ?? ''), type: 'dialogue', timestamp: new Date().toISOString() })),
                      knowledgeBase: a.knowledgeBase || []
                    }));
                  } else {
                    // dict mapping
                    agents = Object.keys(latestAgents).map((k: string, idx: number) => {
                      const a = (latestAgents as any)[k] || {};
                      return {
                        id: `a-${idx}-${a.name || k}`,
                        name: a.name || k,
                        role: a.role || (a.properties || {}).role || '',
                        avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || k)}`,
                        profile: '',
                        llmConfig: { provider: 'mock', model: 'default' },
                        properties: a.properties || {},
                        history: {},
                        memory: (a.short_memory || []).map((m: any, j: number) => ({ id: `m-${idx}-${j}`, round: Number(simSnap?.turns || 0), content: String(m.content ?? ''), type: 'dialogue', timestamp: new Date().toISOString() })),
                        knowledgeBase: a.knowledgeBase || []
                      };
                    });
                  }
                }
              }

              // If we have zero agents from persisted latest_state, try server-side rehydrate
              if (!agents || agents.length === 0) {
                try {
                  const re = await getRehydrate(engineConfig.endpoint, sim.id, token).catch(() => null);
                  if (re && typeof re === 'object') {
                    const nodesRaw2 = (re.nodes || []) as any[];
                    const nodes2 = nodesRaw2.map((n: any) => ({
                      id: String(n.id),
                      display_id: String(n.id),
                      parentId: n.parent == null ? null : String(n.parent),
                      name: t('simPage.nodeId', { id: n.id }),
                      depth: n.depth,
                      isLeaf: (n.depth || 0) === (Math.max(...(nodesRaw2.map((x: any) => x.depth || 0))) || 0),
                      status: 'completed',
                      timestamp: new Date().toLocaleTimeString(),
                      worldTime: new Date().toISOString(),
                      meta: n.meta || {}
                    }));

                    let agents2: any[] = [];
                    try {
                      const firstNode = nodesRaw2.find((n: any) => Number(n.id) === Number(nodes2[0]?.id));
                      const simSnap2 = firstNode?.sim || {};
                      const latestAgents2 = simSnap2?.agents || re.agents || [];
                      if (Array.isArray(latestAgents2)) {
                        agents2 = latestAgents2.map((a: any, idx: number) => ({
                          id: `a-${idx}-${a.name}`,
                          name: a.name,
                          role: a.role || (a.properties || {}).role || '',
                          avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || String(idx))}`,
                          profile: '',
                          llmConfig: { provider: 'mock', model: 'default' },
                          properties: a.properties || {},
                          history: {},
                          memory: (a.short_memory || []).map((m: any, j: number) => ({ id: `m-${idx}-${j}`, round: Number(simSnap2?.turns || 0), content: String(m.content ?? ''), type: 'dialogue', timestamp: new Date().toISOString() })),
                          knowledgeBase: a.knowledgeBase || []
                        }));
                      } else if (latestAgents2 && typeof latestAgents2 === 'object') {
                        agents2 = Object.keys(latestAgents2).map((k: string, idx: number) => {
                          const a = (latestAgents2 as any)[k] || {};
                          return {
                            id: `a-${idx}-${a.name || k}`,
                            name: a.name || k,
                            role: a.role || (a.properties || {}).role || '',
                            avatarUrl: `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(a.name || k)}`,
                            profile: '',
                            llmConfig: { provider: 'mock', model: 'default' },
                            properties: a.properties || {},
                            history: {},
                            memory: (a.short_memory || []).map((m: any, j: number) => ({ id: `m-${idx}-${j}`, round: Number(simSnap2?.turns || 0), content: String(m.content ?? ''), type: 'dialogue', timestamp: new Date().toISOString() })),
                            knowledgeBase: a.knowledgeBase || []
                          };
                        });
                      }
                    } catch (e) {
                      console.warn('rehydrate parsing failed', e);
                    }

                    if (agents2 && agents2.length > 0) {
                      useSimulationStore.setState({
                        currentSimulation: sim,
                        nodes: nodes2,
                        selectedNodeId: nodes2[0]?.id ?? null,
                        agents: agents2,
                        rawEvents: []
                      } as any);
                      return;
                    }
                  }
                } catch (e) {
                  console.warn('rehydrate request failed', e);
                }
              }

              useSimulationStore.setState({
                currentSimulation: sim,
                nodes,
                selectedNodeId: nodes[0]?.id ?? null,
                agents: agents,
                rawEvents: []
              } as any);

              // Attempt to restore events/logs for the selected node when backend is reachable
              const base = engineConfig.endpoint;
              const selectedNodeNumeric = nodes[0]?.id ? Number(nodes[0].id) : null;
              if (selectedNodeNumeric != null && Number.isFinite(selectedNodeNumeric)) {
                try {
                  const events = await getSimEvents(base, sim.id, selectedNodeNumeric, token).catch(() => []);
                  useSimulationStore.setState({ rawEvents: events || [] } as any);
                } catch (e) {
                  console.warn('latest_state events fetch failed', e);
                }
              }

              return;
            }
          } catch (e) {
            console.warn('latest_state fallback failed', e);
          }

          // final fallback: just set simulation
          useSimulationStore.setState({ currentSimulation: sim } as any);
      } catch (e) {
        console.warn('Failed to load simulation on mount', e);
      }
    })();
  }, [simIdParam, hasRestored, isAuthenticated]);

  // Load providers when authenticated
  React.useEffect(() => {
    if (hasRestored && isAuthenticated) {
      useSimulationStore.getState().loadProviders();
    }
  }, [hasRestored, isAuthenticated]);

  React.useEffect(() => {
    if (simIdParam || !hasRestored || !isAuthenticated || !currentSimulation?.id) return;

    navigate(`/simulations/${currentSimulation.id}`, { replace: true });
  }, [simIdParam, hasRestored, isAuthenticated, currentSimulation?.id, navigate]);

  // Auto-open experiment builder when creating a new simulation
  React.useEffect(() => {
    if (!simIdParam && hasRestored && isAuthenticated && !currentSimulation?.id) {
      const { isWizardOpen, toggleWizard } = useSimulationStore.getState();
      if (!isWizardOpen) {
        toggleWizard(true);
      }
    }
  }, [simIdParam, hasRestored, isAuthenticated, currentSimulation?.id]);

  const activeTab = useSimulationStore((s) => s.activeTab);

  React.useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      if (!isResizingRailRef.current) return;
      const nextWidth = Math.min(180, Math.max(88, event.clientX));
      setRailWidth(nextWidth);
    };

    const handleMouseUp = () => {
      isResizingRailRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  return (
    <div className="flex h-screen" style={{ background: 'var(--ss-workspace-bg)' }}>
      <div className="relative flex">
        <TabRail width={railWidth} />
        <button
          type="button"
          aria-label={t("simPage.resizeRail", { defaultValue: "Resize rail" })}
          onMouseDown={() => {
            isResizingRailRef.current = true;
            document.body.style.cursor = "col-resize";
            document.body.style.userSelect = "none";
          }}
          className="absolute top-0 right-[-5px] h-full w-[10px] cursor-col-resize"
          style={{ background: "transparent" }}
        >
          <span
            className="absolute top-1/2 right-[4px] h-12 w-px -translate-y-1/2"
            style={{ background: "var(--ss-workspace-border)" }}
          />
        </button>
      </div>

      <div className="flex-1 flex flex-col overflow-hidden">
        {activeTab === 'workspace' && (
          <>
            <div className="flex-1 overflow-hidden relative px-3 pb-3 pt-2">
              <div className="flex gap-3 h-full">
                <div className="w-[40%] flex flex-col">
                  <SimTree layoutDirection="vertical" />
                </div>
                <div className="flex-1 flex flex-col">
                  {isCompareMode ? (
                    <React.Suspense fallback={<RouteLoading compact />}><ComparisonView /></React.Suspense>
                  ) : <LogViewer />}
                </div>
              </div>
              <PeekOverlay />
            </div>
          </>
        )}

        {activeTab === 'agents' && (
          <div className="flex-1 overflow-hidden">
            <Sidebar />
          </div>
        )}

        {activeTab === 'intervention' && (
          <div className="flex-1 overflow-hidden">
            <React.Suspense fallback={<RouteLoading compact />}>
              <InterventionTab />
            </React.Suspense>
          </div>
        )}

        {activeTab === 'analyse' && (
          <div className="flex-1 overflow-hidden">
            <React.Suspense fallback={<RouteLoading compact />}>
              <AnalyseTab />
            </React.Suspense>
          </div>
        )}
      </div>

      {/* Modals */}
      <React.Suspense fallback={<RouteLoading compact />}>
        {workspaceOverlayMounts.experimentBuilder ? <ExperimentBuilderModal /> : null}
        {workspaceOverlayMounts.help ? <HelpModal /> : null}
        {workspaceOverlayMounts.analytics ? <AnalyticsPanel /> : null}
        {workspaceOverlayMounts.export ? <ExportModal /> : null}
        {workspaceOverlayMounts.experimentDesigner ? <ExperimentDesignModal /> : null}
        {workspaceOverlayMounts.timeSettings ? <TimeSettingsModal /> : null}
        {workspaceOverlayMounts.templateSave ? <TemplateSaveModal /> : null}
        {workspaceOverlayMounts.networkEditor ? <NetworkEditorModal /> : null}
        {workspaceOverlayMounts.report ? <ReportModal /> : null}
        {workspaceOverlayMounts.globalKnowledge ? <GlobalKnowledgePanel /> : null}
        {workspaceOverlayMounts.guide ? <GuideAssistant /> : null}
      </React.Suspense>
      <SyncModal />
      <ToastContainer />
    </div>
  );
};

export default SimulationPage;
export { SimulationPage };
