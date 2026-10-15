import React from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  Filter,
  GitFork,
  LogOut,
  Map as MapIcon,
  Moon,
  MousePointer2,
  Search,
  Sun,
  Trash2,
} from "lucide-react";
import { BrandLogo } from "../components/BrandLogo";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { SimTree } from "../components/SimTree";
import { ForkFromCheckpointModal, RecoveryModal } from "../components/TopologyForkRecoveryModals";
import { ToastContainer } from "../components/Toast";
import { useSimulationStore } from "../store";
import { compareBranches } from "../services/experiments";
import "../styles/routes/topology.css";
import { useAuthStore } from "../store/auth";
import { useThemeStore } from "../store/theme";
import type { SimNode } from "../types";
import { buildBranchContextHref, readBranchContext } from "../utils/branchContext";

const STATUS_FILTERS: Array<SimNode["status"]> = ["running", "completed", "failed", "pending"];

const sortNodes = (left: SimNode, right: SimNode) =>
  String(left.display_id || left.id).localeCompare(String(right.display_id || right.id), undefined, {
    numeric: true,
    sensitivity: "base",
  });

const statusClassName = (status: SimNode["status"]) => `ss-topology__status-dot is-${status}`;

const includeAncestors = (nodeMap: globalThis.Map<string, SimNode>, ids: Set<string>, id: string | null) => {
  let current = id ? nodeMap.get(id) || null : null;
  while (current) {
    ids.add(current.id);
    current = current.parentId ? nodeMap.get(current.parentId) || null : null;
  }
};

const BranchSummaryCard: React.FC<{
  t: (key: string) => string;
  title: string;
  node: SimNode | null;
  highlight?: "selected" | "compare";
}> = ({ t, title, node, highlight }) => (
  <div className={`ss-topology__summary-card ${highlight ? `is-${highlight}` : ""}`}>
    <div className="ss-topology__summary-kicker">{title}</div>
    {node ? (
      <>
        <div className="ss-topology__summary-title">{node.name}</div>
        <div className="ss-topology__summary-meta">{node.display_id || node.id}</div>
        <div className="ss-topology__summary-status">
          <span className={statusClassName(node.status)} aria-hidden />
          <span>{t(`topologyExplorer.status.${node.status}`)}</span>
        </div>
      </>
    ) : (
      <div className="ss-topology__summary-empty">{t("topologyExplorer.valueUnavailable")}</div>
    )}
  </div>
);

type QuantState =
  | { status: "idle" }
  | { status: "running" }
  | { status: "done"; report: any }
  | { status: "error"; error: string };

const quantReportView = (t: (key: string) => string, report: any, branchId: string) => {
  if (!report) return <div className="ss-path__empty">{t("topologyExplorer.quant.noData")}</div>;
  const worlds: any[] = report.worlds || [];
  const branch = worlds.find((w) => String(w.id) === branchId);
  const movers: any[] = (report.movers || {})[branchId] || [];
  const deltas: any[] = report.deltas || [];
  return (
    <div className="ss-topology__detail-card">
      <div className="ss-topology__detail-line">
        <span>{t("topologyExplorer.quant.splitPoint")}</span>
        <strong>
          {branch && branch.split_step != null
            ? `${t("topologyExplorer.quant.step")} ${branch.split_step}`
            : "—"}
        </strong>
      </div>
      {worlds.map((world) => (
        <div key={world.id} className="ss-topology__detail-line">
          <span>{world.label || world.id}</span>
          <strong>
            {world.has_data && world.divergence_final != null
              ? Number(world.divergence_final).toFixed(4)
              : "—"}
          </strong>
        </div>
      ))}
      {movers.length > 0 ? (
        <div className="ss-topology__detail-card">
          <div className="ss-topology__detail-card-title">{t("topologyExplorer.quant.movers")}</div>
          {movers.slice(0, 10).map((mover, index) => (
            <div key={`${mover.agent_id}-${index}`} className="ss-topology__detail-line">
              <span>
                {t("topologyExplorer.quant.agent")} {mover.agent_id}
              </span>
              <strong>
                {mover.top_metric} {mover.distance != null ? `(${Number(mover.distance).toFixed(4)})` : ""}
              </strong>
            </div>
          ))}
        </div>
      ) : null}
      {deltas.length > 0 ? (
        <table className="ss-topology__quant-table">
          <thead>
            <tr>
              <th>{t("topologyExplorer.quant.metric")}</th>
              <th>{t("topologyExplorer.quant.baseline")}</th>
              <th>{t("topologyExplorer.quant.delta")}</th>
            </tr>
          </thead>
          <tbody>
            {deltas.map((row, index) => (
              <tr key={`${row.world_id}-${row.metric}-${index}`}>
                <td>{row.metric}</td>
                <td>{Number(row.baseline_final).toFixed(4)}</td>
                <td>{Number(row.delta_final).toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
};

const TopologyExplorerPage: React.FC = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const simIdParam = params.id || null;

  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const nodes = useSimulationStore((state) => state.nodes);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const compareTargetNodeId = useSimulationStore((state) => state.compareTargetNodeId);
  const isCompareMode = useSimulationStore((state) => state.isCompareMode);
  const engineConfig = useSimulationStore((state) => state.engineConfig);
  const selectNode = useSimulationStore((state) => state.selectNode);
  const setCompareTarget = useSimulationStore((state) => state.setCompareTarget);
  const toggleCompareMode = useSimulationStore((state) => state.toggleCompareMode);
  const loadSimulationById = useSimulationStore((state) => state.loadSimulationById);
  const branchSimulation = useSimulationStore((state) => state.branchSimulation);
  const deleteNode = useSimulationStore((state) => state.deleteNode);
  const isGenerating = useSimulationStore((state: any) => state.isGenerating);

  const hasRestored = useAuthStore((state) => state.hasRestored);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.clearSession);
  const themeMode = useThemeStore((state) => state.mode);
  const toggleTheme = useThemeStore((state) => state.toggle);

  const [searchQuery, setSearchQuery] = React.useState("");
  const [statusFilter, setStatusFilter] = React.useState<SimNode["status"] | "all">("all");
  const [forkDialogOpen, setForkDialogOpen] = React.useState(false);
  const [recoveryDialogOpen, setRecoveryDialogOpen] = React.useState(false);
  const [quantState, setQuantState] = React.useState<QuantState>({ status: "idle" });

  React.useEffect(() => {
    setQuantState({ status: "idle" });
  }, [selectedNodeId, compareTargetNodeId]);

  React.useEffect(() => {
    if (!simIdParam) return;
    if (!hasRestored || !isAuthenticated) return;
    if (currentSimulation && String(currentSimulation.id) === String(simIdParam) && nodes.length > 0) return;
    void loadSimulationById(String(simIdParam));
  }, [
    currentSimulation,
    hasRestored,
    isAuthenticated,
    loadSimulationById,
    nodes.length,
    simIdParam,
  ]);

  React.useEffect(() => {
    if (!nodes.length) return;

    const currentParams = new URLSearchParams(location.search);
    const { nodeId, compareId } = readBranchContext(currentParams);
    const hasNode = nodeId && nodes.some((node) => node.id === nodeId);
    const hasCompare = compareId && nodes.some((node) => node.id === compareId) && compareId !== nodeId;

    if (hasNode && nodeId !== selectedNodeId) {
      selectNode(nodeId);
    }

    if (hasCompare && compareId !== compareTargetNodeId) {
      setCompareTarget(compareId);
    }

    if (!hasCompare && compareTargetNodeId) {
      setCompareTarget(null);
    }

    if (isCompareMode !== Boolean(hasCompare)) {
      toggleCompareMode(Boolean(hasCompare));
    }
  }, [
    location.search,
    nodes,
    selectNode,
    setCompareTarget,
    toggleCompareMode,
  ]);

  React.useEffect(() => {
    if (!simIdParam || !selectedNodeId) return;
    if (!currentSimulation || String(currentSimulation.id) !== String(simIdParam)) return;

    const currentParams = new URLSearchParams(window.location.search);
    const { nodeId, compareId } = readBranchContext(currentParams);
    const nextCompare = compareTargetNodeId && isCompareMode ? compareTargetNodeId : null;

    if (nodeId === selectedNodeId && compareId === nextCompare) return;

    const nextParams = new URLSearchParams(currentParams);
    nextParams.set("node", selectedNodeId);
    if (nextCompare) {
      nextParams.set("compare", nextCompare);
    } else {
      nextParams.delete("compare");
    }

    const nextQuery = nextParams.toString();
    const nextUrl = nextQuery ? `${window.location.pathname}?${nextQuery}` : window.location.pathname;
    window.history.replaceState(window.history.state, "", nextUrl);
  }, [
    compareTargetNodeId,
    currentSimulation,
    isCompareMode,
    selectedNodeId,
    simIdParam,
  ]);

  const nodeMap = React.useMemo(
    () => new globalThis.Map(nodes.map((node) => [node.id, node])),
    [nodes],
  );

  const filteredNodes = React.useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query && statusFilter === "all") {
      return nodes;
    }

    const includedIds = new Set<string>();
    nodes
      .filter((node) => {
        const matchesStatus = statusFilter === "all" || node.status === statusFilter;
        const haystack = `${node.display_id} ${node.name}`.toLowerCase();
        const matchesQuery = !query || haystack.includes(query);
        return matchesStatus && matchesQuery;
      })
      .forEach((node) => includeAncestors(nodeMap, includedIds, node.id));

    includeAncestors(nodeMap, includedIds, selectedNodeId);
    includeAncestors(nodeMap, includedIds, compareTargetNodeId);

    return nodes.filter((node) => includedIds.has(node.id));
  }, [compareTargetNodeId, nodeMap, nodes, searchQuery, selectedNodeId, statusFilter]);

  const selectedNode = React.useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) || nodes[0] || null,
    [nodes, selectedNodeId],
  );
  const compareTargetNode = React.useMemo(
    () => nodes.find((node) => node.id === compareTargetNodeId) || null,
    [nodes, compareTargetNodeId],
  );
  const parentNode = React.useMemo(
    () => nodes.find((node) => node.id === selectedNode?.parentId) || null,
    [nodes, selectedNode?.parentId],
  );
  const childNodes = React.useMemo(
    () => nodes.filter((node) => node.parentId === selectedNode?.id).sort(sortNodes),
    [nodes, selectedNode?.id],
  );
  const statusCounts = React.useMemo(() => {
    const counts: Record<string, number> = { all: nodes.length };
    STATUS_FILTERS.forEach((status) => {
      counts[status] = nodes.filter((node) => node.status === status).length;
    });
    return counts;
  }, [nodes]);

  const selectedNodeHasCheckpoint = Boolean(
    (selectedNode?.meta as Record<string, unknown> | null | undefined)?.checkpoint,
  );
  const selectedNodeFailed = selectedNode?.status === "failed";

  const handleOpenControlRoom = () => {
    if (!simIdParam) return;
    navigate(
      buildBranchContextHref(
        `/simulations/${simIdParam}`,
        selectedNodeId,
        isCompareMode ? compareTargetNodeId : null,
      ),
    );
  };

  const handleToggleComparePrep = () => {
    if (isCompareMode) {
      toggleCompareMode(false);
      setCompareTarget(null);
      return;
    }
    toggleCompareMode(true);
  };

  const handleDelete = () => {
    if (!selectedNodeId) return;
    if (window.confirm(t("components.simTree.confirmDelete"))) {
      void deleteNode();
    }
  };

  const handleQuantCompare = () => {
    if (!simIdParam || !selectedNode || !compareTargetNode) return;
    if (compareTargetNode.status !== "completed") {
      setQuantState({ status: "error", error: t("topologyExplorer.quant.errorUnfinished") });
      return;
    }
    setQuantState({ status: "running" });
    compareBranches(String(simIdParam), Number(selectedNode.id), [Number(compareTargetNode.id)])
      .then((res) => {
        if (res && res.report) {
          setQuantState({ status: "done", report: res.report });
        } else {
          setQuantState({ status: "error", error: res?.error || t("topologyExplorer.quant.errorFailed") });
        }
      })
      .catch((err) => {
        setQuantState({ status: "error", error: err?.message || t("topologyExplorer.quant.errorFailed") });
      });
  };

  const showLoadingState =
    Boolean(simIdParam) && (!currentSimulation || String(currentSimulation.id) !== String(simIdParam));

  return (
    <div className="ss-workspace ss-topology-page">
      <div className="ss-workspace__chrome">
        <div className="ss-workspace__topbar">
          <div className="flex flex-wrap items-center gap-4">
            <div className="ss-workspace__brand">
              <BrandLogo
                subtitle={t("topologyExplorer.topologyExplorer")}
                titleClassName="text-sm font-semibold tracking-tight text-[var(--ss-workspace-heading)]"
              />
            </div>

            <nav className="ss-workspace__nav">
              <Link to="/dashboard" className="ss-workspace__nav-link">
                {t("nav.dashboard")}
              </Link>
              <Link to="/simulations/create" className="ss-workspace__nav-link">
                {t("nav.create")}
              </Link>
              <Link to="/simulations/new" className="ss-workspace__nav-link">
                {t("nav.workbench")}
              </Link>
              <Link to="/simulations/saved" className="ss-workspace__nav-link">
                {t("nav.saved")}
              </Link>
              <Link to="/settings" className="ss-workspace__nav-link">
                {t("nav.settings")}
              </Link>
            </nav>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button onClick={toggleTheme} className="ss-icon-button" title={t("components.navBar.toggleTheme")}>
              {themeMode === "dark" ? <Moon size={16} /> : <Sun size={16} />}
            </button>
            <LanguageSwitcher />
            <div className="ss-pill ss-pill--quiet">{String(user?.email || "")}</div>
            <button onClick={logout} className="ss-icon-button" title={t("nav.signout")}>
              <LogOut size={14} />
              <span className="hidden sm:inline">{t("nav.signout")}</span>
            </button>
          </div>
        </div>

        <div className="ss-topology__hero">
          <div className="ss-topology__hero-main">
            <div className="ss-kicker">{t("topologyExplorer.topologyExplorer")}</div>
            <h1 className="ss-workspace__hero-title">
              {currentSimulation?.name || t("simulationWorkspace.titleFallback")}
            </h1>
            <p className="ss-workspace__hero-copy">{t("topologyExplorer.subtitle")}</p>
          </div>

          <div className="ss-topology__hero-actions">
            <button onClick={handleOpenControlRoom} className="ss-button">
              <ArrowLeft size={16} />
              {t("topologyExplorer.returnToExperiment")}
            </button>
          </div>
        </div>
      </div>

      <div className="ss-workspace__main">
        {showLoadingState ? (
          <div className="ss-workspace__panel ss-workspace__panel--stage flex h-full items-center justify-center px-6">
            <div className="max-w-lg text-center">
              <div className="ss-kicker">{t("topologyExplorer.topologyExplorer")}</div>
              <h2 className="mt-3 font-[var(--font-display)] text-3xl font-semibold tracking-[-0.05em] text-[var(--ss-workspace-heading)]">
                {t("simulationWorkspace.loadingTitle")}
              </h2>
              <p className="mt-3 text-sm leading-7 text-[var(--ss-workspace-muted)]">
                {t("simulationWorkspace.loadingBody")}
              </p>
            </div>
          </div>
        ) : (
          <div className="ss-topology">
            <aside className="ss-workspace__panel ss-topology__rail">
              <div className="ss-workspace__panel-header">
                <div className="ss-kicker">{t("topologyExplorer.leftRailLabel")}</div>
                <h2 className="ss-workspace__panel-title mt-2">{t("topologyExplorer.overview")}</h2>
                <p className="ss-workspace__panel-copy">{t("topologyExplorer.overviewHint")}</p>
              </div>

              <div className="ss-topology__rail-body">
                <button onClick={handleOpenControlRoom} className="ss-button-secondary">
                  <ArrowLeft size={15} />
                  {t("topologyExplorer.openInControlRoom")}
                </button>

                <button onClick={handleToggleComparePrep} className={`ss-button-secondary ${isCompareMode ? "is-active" : ""}`}>
                  <MousePointer2 size={15} />
                  {isCompareMode ? t("topologyExplorer.exitComparePrep") : t("topologyExplorer.prepareCompare")}
                </button>

                <div className="ss-topology__search">
                  <Search size={15} />
                  <input
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                    placeholder={t("topologyExplorer.searchNodes")}
                  />
                </div>

                <section className="ss-topology__filter-section">
                  <div className="ss-topology__filter-title">
                    <Filter size={14} />
                    {t("topologyExplorer.branchStateFilters")}
                  </div>
                  <div className="ss-topology__status-list">
                    <button
                      onClick={() => setStatusFilter("all")}
                      className={`ss-topology__status-chip ${statusFilter === "all" ? "is-active" : ""}`}
                    >
                      <span>{t("common.overview")}</span>
                      <strong>{statusCounts.all}</strong>
                    </button>
                    {STATUS_FILTERS.map((status) => (
                      <button
                        key={status}
                        onClick={() => setStatusFilter(status)}
                        className={`ss-topology__status-chip ${statusFilter === status ? "is-active" : ""}`}
                      >
                        <span className={statusClassName(status)} aria-hidden />
                        <span>{t(`topologyExplorer.status.${status}`)}</span>
                        <strong>{statusCounts[status]}</strong>
                      </button>
                    ))}
                  </div>
                </section>

                <section className="ss-topology__filter-section">
                  <div className="ss-topology__filter-title">{t("topologyExplorer.selectionSummary")}</div>
                  <BranchSummaryCard
                    t={t}
                    title={t("topologyExplorer.activeBranch")}
                    node={selectedNode}
                    highlight="selected"
                  />
                  {compareTargetNode ? (
                    <BranchSummaryCard
                      t={t}
                      title={t("topologyExplorer.compareBranch")}
                      node={compareTargetNode}
                      highlight="compare"
                    />
                  ) : null}
                </section>
              </div>
            </aside>

            <div className="ss-topology__canvas">
              <SimTree nodesOverride={filteredNodes} />
            </div>

            <aside className="ss-workspace__panel ss-topology__detail">
              <div className="ss-workspace__panel-header">
                <div className="ss-kicker">{t("topologyExplorer.selectedBranchDetail")}</div>
                <h2 className="ss-workspace__panel-title mt-2">{selectedNode?.name || t("topologyExplorer.valueUnavailable")}</h2>
                <p className="ss-workspace__panel-copy">{t("topologyExplorer.detailHint")}</p>
              </div>

              <div className="ss-topology__detail-body">
                <div className="ss-topology__detail-grid">
                  <div className="ss-topology__detail-stat">
                    <span>{t("simulationWorkspace.metrics.branch")}</span>
                    <strong>{selectedNode?.display_id || t("topologyExplorer.valueUnavailable")}</strong>
                  </div>
                  <div className="ss-topology__detail-stat">
                    <span>{t("topologyExplorer.branchDepth")}</span>
                    <strong>{selectedNode?.depth ?? 0}</strong>
                  </div>
                  <div className="ss-topology__detail-stat">
                    <span>{t("topologyExplorer.childBranches")}</span>
                    <strong>{childNodes.length}</strong>
                  </div>
                  <div className="ss-topology__detail-stat">
                    <span>{t("topologyExplorer.parentBranch")}</span>
                    <strong>{parentNode?.display_id || t("topologyExplorer.valueUnavailable")}</strong>
                  </div>
                </div>

                <div className="ss-topology__detail-card">
                  <div className="ss-topology__detail-card-title">{t("topologyExplorer.branchState")}</div>
                  <div className="ss-topology__detail-line">
                    <span>{t("common.status")}</span>
                    <strong className="capitalize">{selectedNode?.status ? t(`topologyExplorer.status.${selectedNode.status}`) : t("topologyExplorer.valueUnavailable")}</strong>
                  </div>
                  <div className="ss-topology__detail-line">
                    <span>{t("simulationWorkspace.metrics.worldTime")}</span>
                    <strong>{selectedNode?.worldTime || t("topologyExplorer.valueUnavailable")}</strong>
                  </div>
                  <div className="ss-topology__detail-line">
                    <span>{t("topologyExplorer.visibleNodes")}</span>
                    <strong>{filteredNodes.length}</strong>
                  </div>
                </div>

                <div className="ss-topology__detail-card">
                  <div className="ss-topology__detail-card-title">{t("topologyExplorer.branchActions")}</div>
                  <div className="ss-topology__detail-actions">
                    <button
                      onClick={() => void branchSimulation()}
                      disabled={!selectedNodeId || isGenerating || isCompareMode}
                      className="ss-button-secondary"
                    >
                      <GitFork size={15} />
                      {t("simulationWorkspace.branch")}
                    </button>
                    <button
                      onClick={() => setForkDialogOpen(true)}
                      disabled={!selectedNodeHasCheckpoint || isGenerating || isCompareMode}
                      className="ss-button-secondary"
                    >
                      <GitFork size={15} />
                      {t("topologyExplorer.forkDialog.button")}
                    </button>
                    <button onClick={handleOpenControlRoom} className="ss-button-secondary">
                      <MapIcon size={15} />
                      {t("topologyExplorer.openInControlRoom")}
                    </button>
                    <button
                      onClick={() => setRecoveryDialogOpen(true)}
                      disabled={!selectedNodeFailed || isGenerating}
                      className="ss-button-secondary ss-button-secondary--danger"
                    >
                      {t("topologyExplorer.recoveryDialog.button")}
                    </button>
                    <button
                      onClick={handleDelete}
                      disabled={!selectedNodeId || selectedNodeId === "root" || isGenerating}
                      className="ss-button-secondary ss-button-secondary--danger"
                    >
                      <Trash2 size={15} />
                      {t("controlRoom.removeNode")}
                    </button>
                  </div>
                </div>

                {compareTargetNode ? (
                  <div className="ss-topology__detail-card">
                    <div className="ss-topology__detail-card-title">{t("topologyExplorer.compareReady")}</div>
                    <p className="ss-topology__detail-copy">{t("topologyExplorer.compareReadyHint")}</p>
                    <div className="ss-topology__compare-stack">
                      <BranchSummaryCard
                        t={t}
                        title={t("topologyExplorer.activeBranch")}
                        node={selectedNode}
                        highlight="selected"
                      />
                      <BranchSummaryCard
                        t={t}
                        title={t("topologyExplorer.compareBranch")}
                        node={compareTargetNode}
                        highlight="compare"
                      />
                    </div>
                  </div>
                ) : null}

                {compareTargetNode ? (
                  <div className="ss-topology__detail-card">
                    <div className="ss-topology__detail-card-title">{t("topologyExplorer.quant.title")}</div>
                    <p className="ss-topology__detail-copy">{t("topologyExplorer.quant.hint")}</p>
                    <div className="ss-topology__detail-actions">
                      <button
                        onClick={handleQuantCompare}
                        disabled={quantState.status === "running" || selectedNode?.status !== "completed" || compareTargetNode.status !== "completed"}
                        className="ss-button-secondary"
                      >
                        {quantState.status === "running" ? t("topologyExplorer.quant.running") : t("topologyExplorer.quant.run")}
                      </button>
                    </div>
                    {quantState.status === "error" ? (
                      <div className="ss-path__empty" role="alert">{quantState.error}</div>
                    ) : null}
                    {quantState.status === "done"
                      ? quantReportView(t, quantState.report, String(compareTargetNode.id))
                      : null}
                  </div>
                ) : null}

                <div className="ss-topology__detail-card">
                  <div className="ss-topology__detail-card-title">{t("topologyExplorer.immediateChildren")}</div>
                  {childNodes.length > 0 ? (
                    <div className="ss-topology__child-list">
                      {childNodes.map((node) => (
                        <button key={node.id} onClick={() => selectNode(node.id)} className="ss-topology__child-item">
                          <span className={statusClassName(node.status)} aria-hidden />
                          <span className="ss-topology__child-main">
                            <strong>{node.display_id}</strong>
                            <span>{node.name}</span>
                          </span>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="ss-path__empty">{t("controlRoom.noChildBranches")}</div>
                  )}
                </div>
              </div>
            </aside>
          </div>
        )}
      </div>

      <ToastContainer />
      {forkDialogOpen && simIdParam && (
        <ForkFromCheckpointModal
          node={selectedNode}
          base={{ endpoint: engineConfig?.endpoint || "/api", token: engineConfig?.token }}
          simulationId={String(simIdParam)}
          onClose={() => setForkDialogOpen(false)}
          onForked={(children) => {
            setForkDialogOpen(false);
            (useSimulationStore.getState() as any).addNotification?.(
              "success",
              t("topologyExplorer.forkDialog.done", { count: children.length }),
            );
            void loadSimulationById(String(simIdParam));
          }}
          onError={(message) => {
            (useSimulationStore.getState() as any).addNotification?.("error", message);
          }}
        />
      )}
      {recoveryDialogOpen && simIdParam && (
        <RecoveryModal
          node={selectedNode}
          base={{ endpoint: engineConfig?.endpoint || "/api", token: engineConfig?.token }}
          simulationId={String(simIdParam)}
          onClose={() => setRecoveryDialogOpen(false)}
          onRecovered={(child) => {
            setRecoveryDialogOpen(false);
            (useSimulationStore.getState() as any).addNotification?.(
              "success",
              t("topologyExplorer.recoveryDialog.done", { child }),
            );
            void loadSimulationById(String(simIdParam));
          }}
          onError={(message) => {
            (useSimulationStore.getState() as any).addNotification?.("error", message);
          }}
        />
      )}
    </div>
  );
};

export default TopologyExplorerPage;
