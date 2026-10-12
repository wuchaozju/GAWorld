import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowRight, FlaskConical, History, Orbit, Play, Radar, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { listProviders } from "../services/providers";
import { listScenes } from "../services/scenes";
import { listSimulations } from "../services/simulations";
import "../styles/routes/product.css";

const getStatusTone = (status: string) => {
  if (status === "active") {
    return "ss-status-chip is-success";
  }
  if (status === "archived") {
    return "ss-status-chip is-neutral";
  }
  return "ss-status-chip is-warning";
};

export function DashboardPage() {
  const { t } = useTranslation();
  const simulationsQuery = useQuery({
    queryKey: ["simulations"],
    queryFn: () => listSimulations(),
  });
  const providersQuery = useQuery({
    queryKey: ["providers"],
    queryFn: () => listProviders(),
  });
  const scenesQuery = useQuery({
    queryKey: ["scenes"],
    queryFn: () => listScenes(),
  });

  const hasProvider = (providersQuery.data ?? []).length > 0;

  const recentSimulations = useMemo(() => {
    const items = [...(simulationsQuery.data ?? [])];
    return items
      .sort((left, right) => {
        const leftTime = new Date(left.created_at).getTime();
        const rightTime = new Date(right.created_at).getTime();
        return rightTime - leftTime;
      })
      .slice(0, 4);
  }, [simulationsQuery.data]);

  const activeSimulation = recentSimulations[0];
  const recentChanges = recentSimulations.slice(activeSimulation ? 1 : 0, 4);
  const scenePreview = (scenesQuery.data ?? []).slice(0, 3);

  const formatDate = (value: string) => new Date(value).toLocaleString();

  const getSceneName = (scene: { type: string; name: string }) =>
    t(`dashboardDesk.sceneTypes.${scene.type}.name`, {
      defaultValue: scene.name,
    });

  const getSceneDescription = (scene: { type: string; description?: string }) =>
    t(`dashboardDesk.sceneTypes.${scene.type}.description`, {
      defaultValue: scene.description || t("dashboardDesk.scenarioEntryHint"),
    });

  const formatSceneName = (simulation: any) => {
    const matched = (scenesQuery.data ?? []).find((scene) => scene.type === simulation.scene_type);
    if (matched) {
      return getSceneName(matched);
    }

    return t(`dashboardDesk.sceneTypes.${simulation.scene_type}.name`, {
      defaultValue: simulation.scene_type,
    });
  };

  return (
    <div className="ss-product-page ss-product-page--dashboard ss-dashboard-page scroll-panel">
      <section className="lab-surface ss-dashboard-page__hero p-6">
        <div className="ss-dashboard-page__hero-grid">
          <div className="ss-dashboard-page__hero-main">
            <div className="kicker">{t("dashboardDesk.eyebrow")}</div>
            <div className="space-y-3">
              <h1 className="display-title m-0">{t("dashboardDesk.title")}</h1>
              <p className="lab-meta max-w-3xl text-[1rem]">{t("dashboardDesk.subtitle")}</p>
            </div>

            <div className="flex flex-wrap gap-3">
              <Link to="/simulations/new" className="button inline-flex items-center gap-2">
                <FlaskConical size={16} />
                {t("dashboardDesk.launchExperiment")}
              </Link>
              <Link to="/simulations/saved" className="button button-ghost inline-flex items-center gap-2">
                <History size={16} />
                {t("dashboardDesk.openArchive")}
              </Link>
            </div>

            {!hasProvider && (
              <div className="lab-inset space-y-3 p-4">
                <div className="lab-label">
                  <span className="lab-dot" />
                  {t("dashboardDesk.providerMissing")}
                </div>
                <div className="section-title">{t("dashboardDesk.providerWarningTitle")}</div>
                <p className="lab-meta">{t("dashboardDesk.providerWarningBody")}</p>
                <Link to="/settings/providers" className="button inline-flex w-fit items-center gap-2">
                  <Sparkles size={16} />
                  {t("dashboardDesk.recommendationSetup")}
                </Link>
              </div>
            )}

            <div className="lab-surface ss-dashboard-page__desk-lab ss-dashboard-page__desk-lab--inline p-5">
              <div className="ss-dashboard-page__desk-lab-grid">
                <div className="ss-dashboard-page__desk-column ss-dashboard-page__desk-column--actions">
                  <div className="ss-dashboard-page__desk-head">
                    <div className="space-y-2">
                      <div className="kicker">{t("dashboardDesk.recommendations")}</div>
                      <div className="section-title">{t("dashboardDesk.recommendations")}</div>
                      <p className="lab-meta">{t("dashboardDesk.recommendationsHint")}</p>
                    </div>
                    <Orbit className="ss-dashboard-page__section-icon" size={20} />
                  </div>

                  <div className="ss-dashboard-page__action-grid">
                    {[
                      {
                        icon: FlaskConical,
                        label: t("dashboardDesk.recommendationNew"),
                        hint: t("dashboardDesk.newExperimentHint"),
                        to: "/simulations/new",
                      },
                      {
                        icon: Radar,
                        label: t("dashboardDesk.recommendationScenes"),
                        hint: t("dashboardDesk.sceneLibraryHint"),
                        to: "/simulations/new",
                      },
                      {
                        icon: Orbit,
                        label: t("dashboardDesk.recommendationNetwork"),
                        hint: t("dashboardDesk.networkHint"),
                        to: "/simulations/new",
                      },
                      {
                        icon: Sparkles,
                        label: t("dashboardDesk.recommendationAnalyze"),
                        hint: t("dashboardDesk.analyzeHint"),
                        to: "/simulations/saved",
                      },
                    ].map((item) => {
                      const Icon = item.icon;
                      return (
                        <Link key={item.label} to={item.to} className="ss-dashboard-page__action-card">
                          <div className="ss-dashboard-page__quick-card-copy">
                            <div className="flex items-center gap-3">
                              <span className="ss-dashboard-page__icon-badge">
                                <Icon size={14} />
                              </span>
                              <span className="ss-dashboard-page__item-title">{item.label}</span>
                            </div>
                            <p className="ss-dashboard-page__quick-card-hint">{item.hint}</p>
                          </div>
                          <ArrowRight size={16} className="ss-dashboard-page__item-arrow" />
                        </Link>
                      );
                    })}
                  </div>
                </div>

                <div className="ss-dashboard-page__desk-column ss-dashboard-page__desk-column--scenes">
                  <div className="ss-dashboard-page__desk-head">
                    <div className="space-y-2">
                      <div className="kicker">{t("dashboardDesk.scenarioEntry")}</div>
                      <div className="section-title">{t("dashboardDesk.scenarioEntry")}</div>
                      <p className="lab-meta">{t("dashboardDesk.scenarioEntryHint")}</p>
                    </div>
                    <Link to="/simulations/new" className="button button-ghost inline-flex items-center gap-2">
                      {t("dashboardDesk.openScenarioLibrary")}
                      <ArrowRight size={16} />
                    </Link>
                  </div>

                  <div className="ss-dashboard-page__scene-grid">
                    {scenePreview.map((scene) => (
                      <Link key={scene.type} to="/simulations/new" className="ss-dashboard-page__scene-card">
                        <div className="space-y-2">
                          <div className="lab-label">{getSceneName(scene)}</div>
                          <div className="ss-dashboard-page__scene-title">{getSceneName(scene)}</div>
                          <p className="lab-meta">{getSceneDescription(scene)}</p>
                        </div>
                        <div className="ss-dashboard-page__meta-row">
                          <span>{t("common.actions")}: {(scene.allowed_actions ?? scene.basic_actions ?? []).length}</span>
                          <ArrowRight size={15} />
                        </div>
                      </Link>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="lab-inset flex flex-col gap-4 p-5 ss-dashboard-page__active-card">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="kicker">{t("dashboardDesk.currentExperiment")}</div>
                <div className="ss-dashboard-page__title">
                  {activeSimulation ? activeSimulation.name : t("dashboardDesk.noRecent")}
                </div>
              </div>
              <span
                className={`${
                  activeSimulation
                    ? getStatusTone(activeSimulation.status)
                    : "ss-status-chip is-neutral"
                }`}
              >
                {activeSimulation
                  ? t(`dashboardDesk.activeStatus.${activeSimulation.status}`)
                  : t("dashboardDesk.activeStatus.unknown")}
              </span>
            </div>

            <p className="lab-meta">{t("dashboardDesk.currentExperimentHint")}</p>

            {activeSimulation ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="lab-inset p-4">
                  <div className="kicker">{t("common.status")}</div>
                  <div className="ss-dashboard-page__metric">{formatSceneName(activeSimulation)}</div>
                  <div className="ss-dashboard-page__muted">{formatDate(activeSimulation.created_at)}</div>
                </div>
                <div className="lab-inset p-4">
                  <div className="kicker">{t("common.autosave")}</div>
                  <div className="ss-dashboard-page__metric">
                    {hasProvider
                      ? t("dashboardDesk.providerReady")
                      : t("dashboardDesk.providerMissing")}
                  </div>
                  <div className="ss-dashboard-page__muted">{t("dashboardDesk.recommendationsHint")}</div>
                </div>
              </div>
            ) : null}

            {!simulationsQuery.isLoading && recentChanges.length > 0 ? (
              <div className="ss-dashboard-page__recent-list">
                <div className="kicker">{t("dashboardDesk.recentChanges")}</div>
                {recentChanges.map((simulation) => (
                  <Link
                    key={simulation.id}
                    to={`/simulations/${simulation.id}`}
                    className="ss-dashboard-page__recent-item"
                  >
                    <div>
                      <div className="ss-dashboard-page__item-title">{simulation.name}</div>
                      <div className="ss-dashboard-page__meta-line">{formatSceneName(simulation)}</div>
                    </div>
                    <ArrowRight size={15} className="ss-dashboard-page__item-arrow" />
                  </Link>
                ))}
              </div>
            ) : null}

            <Link
              to={activeSimulation ? `/simulations/${activeSimulation.id}` : "/simulations/new"}
              className="button inline-flex w-fit items-center gap-2"
            >
              <Play size={16} />
              {activeSimulation
                ? t("dashboardDesk.continueLabel")
                : t("dashboardDesk.launchExperiment")}
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
