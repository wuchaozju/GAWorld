import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Clock3, Copy, Database, Play, Search, SlidersHorizontal, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  copySimulation as apiCopySimulation,
  deleteSimulation as apiDeleteSimulation,
  listSimulations,
  resumeSimulation as apiResumeSimulation,
} from "../services/simulations";
import { TitleCard } from "../components/TitleCard";
import { useSimulationStore } from "../store";
import "../styles/routes/saved.css";

type SavedSimulation = {
  id: string;
  name: string;
  status: string;
  scene_type: string;
  created_at: string;
};

type SortMode = "recent" | "oldest" | "name";

export function SavedSimulationsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const loadSimulationById = useSimulationStore((s) => s.loadSimulationById);
  const addNotification = useSimulationStore((s) => s.addNotification);
  const simulationsQuery = useQuery({
    queryKey: ["simulations"],
    queryFn: () => listSimulations(),
  });

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkMode, setBulkMode] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sceneFilter, setSceneFilter] = useState("all");
  const [sortMode, setSortMode] = useState<SortMode>("recent");

  const simulations = (simulationsQuery.data ?? []) as SavedSimulation[];

  const copySimulation = useMutation({
    mutationFn: async (simulationSlug: string) => apiCopySimulation(simulationSlug),
    onSuccess: (simulation) => {
      queryClient.invalidateQueries({ queryKey: ["simulations"] });
      navigate(`/simulations/${simulation.id}`);
    },
  });

  const resumeSimulation = useMutation({
    mutationFn: async (simulationSlug: string) => apiResumeSimulation(simulationSlug),
    onSuccess: async (_, simulationSlug) => {
      await loadSimulationById(simulationSlug);
      navigate(`/simulations/${simulationSlug}`);
    },
  });

  const deleteSimulation = useMutation({
    mutationFn: async (simulationSlug: string) => apiDeleteSimulation(simulationSlug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["simulations"] });
    },
  });

  const bulkDeleteSimulation = useMutation({
    mutationFn: async (simulationIds: string[]) => {
      const results = await Promise.allSettled(
        simulationIds.map((simulationId) => apiDeleteSimulation(simulationId)),
      );
      const successCount = results.filter((result) => result.status === "fulfilled").length;
      const failedCount = results.length - successCount;
      return { successCount, failedCount };
    },
    onSuccess: ({ successCount, failedCount }) => {
      if (successCount > 0) {
        addNotification(
          "success",
          t("saved.bulkDeleteResult", { success: successCount, failed: failedCount }),
        );
      }
      if (failedCount > 0 && successCount === 0) {
        addNotification(
          "error",
          t("saved.bulkDeleteResult", { success: successCount, failed: failedCount }),
        );
      }
      setSelectedIds([]);
      setBulkMode(false);
      queryClient.invalidateQueries({ queryKey: ["simulations"] });
    },
  });

  useEffect(() => {
    const availableIds = new Set(simulations.map((simulation) => simulation.id));
    setSelectedIds((current) => current.filter((id) => availableIds.has(id)));
    setSelectedId((current) => {
      if (current && availableIds.has(current)) {
        return current;
      }
      return simulations[0]?.id ?? null;
    });
  }, [simulations]);

  const statusOptions = useMemo(
    () => ["all", ...Array.from(new Set(simulations.map((simulation) => simulation.status || "unknown")))],
    [simulations],
  );

  const sceneOptions = useMemo(
    () => ["all", ...Array.from(new Set(simulations.map((simulation) => simulation.scene_type || "unknown")))],
    [simulations],
  );

  const filteredSimulations = useMemo(() => {
    const normalizedSearch = searchTerm.trim().toLowerCase();
    const items = simulations.filter((simulation) => {
      const searchable = `${simulation.name} ${simulation.status} ${simulation.scene_type} ${simulation.id}`.toLowerCase();
      const matchesSearch = !normalizedSearch || searchable.includes(normalizedSearch);
      const matchesStatus = statusFilter === "all" || simulation.status === statusFilter;
      const matchesScene = sceneFilter === "all" || simulation.scene_type === sceneFilter;
      return matchesSearch && matchesStatus && matchesScene;
    });

    return items.sort((left, right) => {
      if (sortMode === "name") {
        return left.name.localeCompare(right.name);
      }
      if (sortMode === "oldest") {
        return new Date(left.created_at).getTime() - new Date(right.created_at).getTime();
      }
      return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
    });
  }, [sceneFilter, searchTerm, simulations, sortMode, statusFilter]);

  const selectedSimulation =
    filteredSimulations.find((simulation) => simulation.id === selectedId) ??
    simulations.find((simulation) => simulation.id === selectedId) ??
    filteredSimulations[0] ??
    null;

  useEffect(() => {
    if (selectedSimulation && selectedSimulation.id !== selectedId) {
      setSelectedId(selectedSimulation.id);
    }
  }, [selectedId, selectedSimulation]);

  const pendingDelete = deleteSimulation.isPending || bulkDeleteSimulation.isPending;
  const selectedCount = selectedIds.length;
  const allSelected =
    filteredSimulations.length > 0 &&
    filteredSimulations.every((simulation) => selectedIds.includes(simulation.id));

  const toggleSelected = (simulationId: string) => {
    setSelectedIds((current) =>
      current.includes(simulationId)
        ? current.filter((id) => id !== simulationId)
        : [...current, simulationId],
    );
  };

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds((current) =>
        current.filter((id) => !filteredSimulations.some((simulation) => simulation.id === id)),
      );
      return;
    }

    const nextSelection = new Set(selectedIds);
    filteredSimulations.forEach((simulation) => nextSelection.add(simulation.id));
    setSelectedIds(Array.from(nextSelection));
  };

  const handleBulkDelete = () => {
    if (!selectedCount) return;
    if (window.confirm(t("saved.confirmBulkDelete", { count: selectedCount }))) {
      bulkDeleteSimulation.mutate(selectedIds);
    }
  };

  const handleDelete = (simulationId: string) => {
    if (window.confirm(t("saved.confirmDelete"))) {
      deleteSimulation.mutate(simulationId);
    }
  };

  const formatDate = (value: string) =>
    new Date(value).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  const formatStatus = (status: string) =>
    t(`saved.statusValues.${status}`, { defaultValue: status });

  return (
    <div className="ss-product-page ss-product-page--archive scroll-panel">
      <TitleCard title={t("saved.title")} subtitle={t("saved.subtitle")} />

      <section className="ss-archive-toolbar ss-surface-muted">
        <div className="ss-archive-toolbar__search">
          <Search size={16} />
          <input
            type="text"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder={t("saved.searchPlaceholder")}
          />
        </div>

        <label className="ss-archive-toolbar__field">
          <span>{t("saved.statusLabel")}</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">{t("saved.allStatuses")}</option>
            {statusOptions
              .filter((item) => item !== "all")
              .map((status) => (
                <option key={status} value={status}>
                  {formatStatus(status)}
                </option>
              ))}
          </select>
        </label>

        <label className="ss-archive-toolbar__field">
          <span>{t("saved.typeLabel")}</span>
          <select value={sceneFilter} onChange={(event) => setSceneFilter(event.target.value)}>
            <option value="all">{t("saved.allTypes")}</option>
            {sceneOptions
              .filter((item) => item !== "all")
              .map((sceneType) => (
                <option key={sceneType} value={sceneType}>
                  {sceneType}
                </option>
              ))}
          </select>
        </label>

        <label className="ss-archive-toolbar__field">
          <span>{t("saved.sortLabel")}</span>
          <select value={sortMode} onChange={(event) => setSortMode(event.target.value as SortMode)}>
            <option value="recent">{t("saved.sortRecent")}</option>
            <option value="oldest">{t("saved.sortOldest")}</option>
            <option value="name">{t("saved.sortName")}</option>
          </select>
        </label>

        <button
          type="button"
          className="ss-button-secondary ss-archive-toolbar__bulk"
          onClick={() => setBulkMode((current) => !current)}
          disabled={pendingDelete}
        >
          <SlidersHorizontal size={15} />
          <span>{bulkMode ? t("saved.closeBulkActions") : t("saved.bulkActions")}</span>
        </button>
      </section>

      <div className="ss-archive-layout">
        <section className="ss-archive-results">
          <div className="ss-archive-results__header">
            <div>
              <div className="kicker">{t("saved.resultsLabel")}</div>
              <h2 className="section-title">{t("saved.title")}</h2>
            </div>
            <div className="ss-pill ss-pill--quiet">{t("saved.selectedCount", { count: filteredSimulations.length })}</div>
          </div>

          {bulkMode ? (
            <div className="ss-archive-bulk ss-surface">
              <label className="ss-archive-bulk__toggle">
                <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} disabled={pendingDelete} />
                <span>{t("saved.selectAll")}</span>
              </label>
              <span className="panel-subtitle">{t("saved.selectedCount", { count: selectedCount })}</span>
              <div className="ss-archive-bulk__actions">
                <button type="button" className="ss-button-secondary small" onClick={() => setBulkMode(false)}>
                  {t("saved.cancelBulkActions")}
                </button>
                <button
                  type="button"
                  className="ss-button-danger small"
                  onClick={handleBulkDelete}
                  disabled={!selectedCount || pendingDelete}
                >
                  {bulkDeleteSimulation.isPending ? t("saved.deleting") : t("saved.bulkDelete")}
                </button>
              </div>
            </div>
          ) : null}

          {simulationsQuery.isLoading ? <div className="card">{t("saved.loading")}</div> : null}
          {simulationsQuery.error ? <div className="card">{t("saved.error")}</div> : null}

          {!simulationsQuery.isLoading && !filteredSimulations.length ? (
            <div className="ss-empty-state ss-surface">
              <div className="ss-empty-state__icon">
                <Database size={20} />
              </div>
              <div className="section-title">{t("saved.emptyTitle")}</div>
              <div className="panel-subtitle">{t("saved.emptyHint")}</div>
            </div>
          ) : null}

          <div className="ss-archive-grid">
            {filteredSimulations.map((simulation) => {
              const isSelected = selectedSimulation?.id === simulation.id;
              const isChecked = selectedIds.includes(simulation.id);
              return (
                <article
                  key={simulation.id}
                  className={`ss-archive-card ss-surface ${isSelected ? "is-selected" : ""}`}
                  onClick={() => setSelectedId(simulation.id)}
                >
                  <div className="ss-archive-card__header">
                    <div className="ss-archive-card__title-group">
                      {bulkMode ? (
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => toggleSelected(simulation.id)}
                          onClick={(event) => event.stopPropagation()}
                          disabled={pendingDelete}
                        />
                      ) : null}
                      <div>
                        <div className="ss-archive-card__title">{simulation.name}</div>
                        <div className="ss-archive-card__meta-line">
                          <span className="ss-status-chip">{formatStatus(simulation.status)}</span>
                          <span>{simulation.scene_type}</span>
                        </div>
                      </div>
                    </div>
                    <div className="ss-archive-card__date">
                      <Clock3 size={14} />
                      <span>{formatDate(simulation.created_at)}</span>
                    </div>
                  </div>

                  <div className="ss-archive-card__meta">
                    <div>
                      <span className="ss-archive-card__meta-label">{t("saved.simulationId")}</span>
                      <strong>{simulation.id}</strong>
                    </div>
                    <div>
                      <span className="ss-archive-card__meta-label">{t("saved.typeLabel")}</span>
                      <strong>{simulation.scene_type}</strong>
                    </div>
                  </div>

                  <div className="ss-archive-card__actions">
                    <button
                      type="button"
                      className="ss-button small"
                      onClick={(event) => {
                        event.stopPropagation();
                        resumeSimulation.mutate(simulation.id);
                      }}
                      disabled={resumeSimulation.isPending || pendingDelete}
                    >
                      <Play size={14} />
                      <span>{t("saved.resume")}</span>
                    </button>
                    <button
                      type="button"
                      className="ss-button-secondary small"
                      onClick={(event) => {
                        event.stopPropagation();
                        copySimulation.mutate(simulation.id);
                      }}
                      disabled={copySimulation.isPending || pendingDelete}
                    >
                      <Copy size={14} />
                      <span>{t("saved.copy")}</span>
                    </button>
                    <button
                      type="button"
                      className="ss-button-danger small"
                      onClick={(event) => {
                        event.stopPropagation();
                        handleDelete(simulation.id);
                      }}
                      disabled={pendingDelete}
                    >
                      <Trash2 size={14} />
                      <span>{t("saved.delete")}</span>
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        <aside className="ss-archive-detail ss-surface-strong">
          {selectedSimulation ? (
            <>
              <div className="ss-archive-detail__header">
                <div className="kicker">{t("saved.detailTitle")}</div>
                <h2 className="section-title">{selectedSimulation.name}</h2>
                <p className="panel-subtitle">{t("saved.detailHint")}</p>
              </div>

              <div className="ss-archive-detail__meta-grid">
                <div className="ss-inset ss-archive-detail__metric">
                  <span>{t("saved.statusLabel")}</span>
                  <strong>{formatStatus(selectedSimulation.status)}</strong>
                </div>
                <div className="ss-inset ss-archive-detail__metric">
                  <span>{t("saved.typeLabel")}</span>
                  <strong>{selectedSimulation.scene_type}</strong>
                </div>
                <div className="ss-inset ss-archive-detail__metric">
                  <span>{t("saved.createdAt")}</span>
                  <strong>{formatDate(selectedSimulation.created_at)}</strong>
                </div>
                <div className="ss-inset ss-archive-detail__metric">
                  <span>{t("saved.simulationId")}</span>
                  <strong>{selectedSimulation.id}</strong>
                </div>
              </div>

              <div className="card">
                <div className="panel-title">{t("saved.selectedTitle")}</div>
                <div className="panel-subtitle">
                  {t("saved.detailBody", { name: selectedSimulation.name })}
                </div>
              </div>

              <div className="ss-archive-detail__actions">
                <button
                  type="button"
                  className="ss-button"
                  onClick={() => resumeSimulation.mutate(selectedSimulation.id)}
                  disabled={resumeSimulation.isPending || pendingDelete}
                >
                  <Play size={15} />
                  <span>{t("saved.resume")}</span>
                </button>
                <button
                  type="button"
                  className="ss-button-secondary"
                  onClick={() => copySimulation.mutate(selectedSimulation.id)}
                  disabled={copySimulation.isPending || pendingDelete}
                >
                  <Copy size={15} />
                  <span>{t("saved.copy")}</span>
                </button>
                <button
                  type="button"
                  className="ss-button-danger"
                  onClick={() => handleDelete(selectedSimulation.id)}
                  disabled={pendingDelete}
                >
                  <Trash2 size={15} />
                  <span>{t("saved.delete")}</span>
                </button>
              </div>
            </>
          ) : (
            <div className="ss-empty-state">
              <div className="ss-empty-state__icon">
                <Database size={20} />
              </div>
              <div className="section-title">{t("saved.emptyTitle")}</div>
              <div className="panel-subtitle">{t("saved.emptyHint")}</div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
