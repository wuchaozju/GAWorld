import React from "react";
import { useTranslation } from "react-i18next";
import { GitBranchPlus, Layers3, Loader2, Play, RefreshCcw, X } from "lucide-react";

import { useSimulationStore } from "../store";
import { treeAdvanceChain, treeAdvanceFrontier, treeAdvanceMulti } from "../services/simulationTree";

export const AdvancedTreeOpsModal: React.FC = () => {
  const { t } = useTranslation();
  const isOpen = useSimulationStore((state) => state.isTreeOpsModalOpen);
  const close = useSimulationStore((state) => state.closeTreeOpsModal);
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const selectedNode = useSimulationStore((state) =>
    state.nodes.find((node) => node.id === state.selectedNodeId) || state.nodes[0] || null,
  );
  const engineConfig = useSimulationStore((state) => state.engineConfig);
  const loadSimulationById = useSimulationStore((state) => state.loadSimulationById);
  const addNotification = useSimulationStore((state) => state.addNotification);

  const [turns, setTurns] = React.useState(1);
  const [count, setCount] = React.useState(2);
  const [onlyMaxDepth, setOnlyMaxDepth] = React.useState(false);
  const [isBusy, setIsBusy] = React.useState(false);

  const simulationId = currentSimulation?.id || null;
  const parentNodeNumeric = selectedNode?.id ? Number(selectedNode.id) : null;
  const hasParent = parentNodeNumeric != null && Number.isFinite(parentNodeNumeric);

  React.useEffect(() => {
    if (!isOpen) return;
    setTurns(1);
    setCount(2);
    setOnlyMaxDepth(false);
    setIsBusy(false);
  }, [isOpen]);

  if (!isOpen) return null;

  const refreshTree = async () => {
    if (!simulationId) return;
    await loadSimulationById(simulationId);
  };

  const getBase = () => engineConfig.endpoint;
  const getToken = () => engineConfig.token;

  const handleFrontier = async () => {
    if (!simulationId) return;
    setIsBusy(true);
    try {
      await treeAdvanceFrontier(getBase(), simulationId, turns, onlyMaxDepth, getToken());
      await refreshTree();
      addNotification?.("success", t("components.advancedTreeOps.frontierAdvanced"));
    } catch (error: any) {
      addNotification?.("error", error?.message || t("components.advancedTreeOps.frontierAdvanceFailed"));
    } finally {
      setIsBusy(false);
    }
  };

  const handleMulti = async () => {
    if (!simulationId || !hasParent) return;
    setIsBusy(true);
    try {
      await treeAdvanceMulti(getBase(), simulationId, parentNodeNumeric, turns, count, getToken());
      await refreshTree();
      addNotification?.("success", t("components.advancedTreeOps.multiAdvanceCompleted"));
    } catch (error: any) {
      addNotification?.("error", error?.message || t("components.advancedTreeOps.multiAdvanceFailed"));
    } finally {
      setIsBusy(false);
    }
  };

  const handleChain = async () => {
    if (!simulationId || !hasParent) return;
    setIsBusy(true);
    try {
      await treeAdvanceChain(getBase(), simulationId, parentNodeNumeric, turns, getToken());
      await refreshTree();
      addNotification?.("success", t("components.advancedTreeOps.chainAdvanceCompleted"));
    } catch (error: any) {
      addNotification?.("error", error?.message || t("components.advancedTreeOps.chainAdvanceFailed"));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <div className="ss-extension-modal">
      <div className="ss-extension-modal__panel ss-extension-modal__panel--medium">
        <div className="ss-extension-modal__header">
          <div className="ss-extension-modal__header-title">
            <div className="ss-extension-modal__header-icon">
              <GitBranchPlus size={18} />
            </div>
            <div className="ss-extension-modal__header-copy">
              <div className="ss-kicker">{t("components.advancedTreeOps.title")}</div>
              <h2>
                {currentSimulation?.name || t("components.advancedTreeOps.currentSimulation")}
              </h2>
            </div>
          </div>
          <button type="button" className="ss-icon-button" onClick={close} aria-label={t("a11y.close")}>
            <X size={16} />
          </button>
        </div>

        <div className="ss-extension-modal__body">
        <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
          <section className="ss-extension-modal__surface p-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-[var(--ss-workspace-heading)]">
              <Play size={15} />
              <span>{t("components.advancedTreeOps.advanceParameters")}</span>
            </div>

            <div className="mt-4 space-y-4">
              <label className="block space-y-2 text-sm text-[var(--ss-workspace-muted)]">
                <span>{t("components.advancedTreeOps.turns")}</span>
                <input
                  type="number"
                  min={1}
                  value={turns}
                  onChange={(event) => setTurns(Math.max(1, Number(event.target.value) || 1))}
                  className="w-full rounded-xl border border-[var(--ss-workspace-border)] bg-transparent px-3 py-2 text-sm text-[var(--ss-workspace-heading)] outline-none"
                />
              </label>

              <label className="block space-y-2 text-sm text-[var(--ss-workspace-muted)]">
                <span>{t("components.advancedTreeOps.count")}</span>
                <input
                  type="number"
                  min={1}
                  value={count}
                  onChange={(event) => setCount(Math.max(1, Number(event.target.value) || 1))}
                  className="w-full rounded-xl border border-[var(--ss-workspace-border)] bg-transparent px-3 py-2 text-sm text-[var(--ss-workspace-heading)] outline-none"
                />
              </label>

              <label className="flex items-center gap-2 text-sm text-[var(--ss-workspace-muted)]">
                <input
                  type="checkbox"
                  checked={onlyMaxDepth}
                  onChange={(event) => setOnlyMaxDepth(event.target.checked)}
                />
                <span>{t("components.advancedTreeOps.onlyMaxDepthFrontier")}</span>
              </label>
            </div>

            <div className="mt-4 rounded-xl border border-dashed border-[var(--ss-workspace-border)] p-3 text-xs leading-6 text-[var(--ss-workspace-muted)]">
              {t("components.advancedTreeOps.hint.frontierRequirements")}
            </div>
          </section>

          <section className="ss-extension-modal__surface flex flex-col gap-3 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-[var(--ss-workspace-heading)]">
              <Layers3 size={15} />
              <span>{t("components.advancedTreeOps.execute")}</span>
            </div>

            <button
              type="button"
              onClick={() => void handleFrontier()}
              disabled={!simulationId || isBusy}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-[var(--ss-workspace-node-selected)] px-4 py-3 text-sm font-semibold text-[#20170a] transition-opacity hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isBusy ? <Loader2 size={15} className="animate-spin" /> : <RefreshCcw size={15} />}
              <span>{t("components.advancedTreeOps.advanceFrontier")}</span>
            </button>

            <button
              type="button"
              onClick={() => void handleMulti()}
              disabled={!simulationId || !hasParent || isBusy}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-[var(--ss-workspace-border)] px-4 py-3 text-sm font-semibold text-[var(--ss-workspace-heading)] transition-colors hover:bg-[var(--ss-workspace-surface)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <GitBranchPlus size={15} />
              <span>{t("components.advancedTreeOps.advanceMulti")}</span>
            </button>

            <button
              type="button"
              onClick={() => void handleChain()}
              disabled={!simulationId || !hasParent || isBusy}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-[var(--ss-workspace-border)] px-4 py-3 text-sm font-semibold text-[var(--ss-workspace-heading)] transition-colors hover:bg-[var(--ss-workspace-surface)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Play size={15} />
              <span>{t("components.advancedTreeOps.advanceChain")}</span>
            </button>

            <div className="mt-auto text-xs leading-6 text-[var(--ss-workspace-muted)]">
              {t("components.advancedTreeOps.hint.autoRefresh")}
            </div>
          </section>
        </div>
        </div>
      </div>
    </div>
  );
};

export default AdvancedTreeOpsModal;