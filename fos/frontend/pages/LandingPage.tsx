/**
 * This page introduces the product and guides people to the main parts of the app.
 * LandingPage shows the welcome areas, the preview media, the capability cards, the example scenes, and the final action choices.
 */

import { useEffect, useRef, useState } from "react";
import {
  Archive,
  ArrowRight,
  ArrowUpRight,
  Eye,
  GitBranch,
  LayoutDashboard,
  Layers3,
  Settings2,
  SlidersHorizontal,
  SquarePlus,
  Waypoints,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useThemeStore } from "../store/theme";
import { getBilibiliEmbedUrl, isBilibiliConfigured } from "../config/video";
import "../styles/routes/landing.css";

import sceneBehaviorImage from "../assets/landing/scene-behavior.png";
import sceneInstitutionImage from "../assets/landing/scene-institution.png";
import sceneInterventionImage from "../assets/landing/scene-intervention.png";
import scenePolicyImage from "../assets/landing/scene-policy.png";
import experimentDesignImage from "../assets/tutorial/07-experiment-design.png";
import realtimeObservationImage from "../assets/tutorial/08-realtime-obs.png";
import networkTopologyImage from "../assets/tutorial/09-network-topology.png";

export function LandingPage() {
  const { t } = useTranslation();
  const mode = useThemeStore((state) => state.mode);
  const hasExternalPreview = isBilibiliConfigured();
  const previewStageRef = useRef<HTMLDivElement | null>(null);
  const [isPreviewActive, setIsPreviewActive] = useState(!hasExternalPreview);
  const themeClass = mode === "dark" ? "is-dark" : "is-light";
  const heroSubtitle = String(t("landing.hero.sub"));
  const heroSubtitleLines = heroSubtitle
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const heroSubtitleSegments =
    heroSubtitleLines.length > 1
      ? heroSubtitleLines
      : heroSubtitle
          .split(/(?<=[,，。.!?；;])/u)
          .map((segment) => segment.trim())
          .filter(Boolean);

  useEffect(() => {
    const sections = document.querySelectorAll<HTMLElement>(".ss-reveal");
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      {
        threshold: 0.18,
        rootMargin: "0px 0px -10% 0px",
      }
    );

    sections.forEach((section) => observer.observe(section));

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!hasExternalPreview || isPreviewActive || !previewStageRef.current) {
      return;
    }

    const previewObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setIsPreviewActive(true);
            previewObserver.disconnect();
          }
        });
      },
      {
        threshold: 0.35,
        rootMargin: "160px 0px",
      }
    );

    previewObserver.observe(previewStageRef.current);

    return () => previewObserver.disconnect();
  }, [hasExternalPreview, isPreviewActive]);

  const heroTags = [
    t("landing.hero.tag1"),
    t("landing.hero.tag2"),
    t("landing.hero.tag3"),
  ];

  const entryCards = [
    {
      to: "/dashboard",
      title: t("landing.entry.dashboardTitle"),
      subtitle: t("landing.entry.dashboardSubtitle"),
      icon: LayoutDashboard,
    },
    {
      to: "/simulations/new",
      title: t("landing.entry.interfaceTitle"),
      subtitle: t("landing.entry.interfaceSubtitle"),
      icon: Layers3,
    },
    {
      to: "/simulations/saved",
      title: t("landing.entry.savedTitle"),
      subtitle: t("landing.entry.savedSubtitle"),
      icon: Archive,
    },
    {
      to: "/settings/providers",
      title: t("landing.entry.settingsTitle"),
      subtitle: t("landing.entry.settingsSubtitle"),
      icon: Settings2,
    },
  ];

  const sceneCards = [
    {
      tone: "policy",
      title: t("landing.scenes.policyTitle"),
      subtitle: t("landing.scenes.policySubtitle"),
      body: t("landing.scenes.policyBody"),
      image: scenePolicyImage,
    },
    {
      tone: "behavior",
      title: t("landing.scenes.behaviorTitle"),
      subtitle: t("landing.scenes.behaviorSubtitle"),
      body: t("landing.scenes.behaviorBody"),
      image: sceneBehaviorImage,
    },
    {
      tone: "institution",
      title: t("landing.scenes.institutionTitle"),
      subtitle: t("landing.scenes.institutionSubtitle"),
      body: t("landing.scenes.institutionBody"),
      image: sceneInstitutionImage,
    },
    {
      tone: "intervention",
      title: t("landing.scenes.interventionTitle"),
      subtitle: t("landing.scenes.interventionSubtitle"),
      body: t("landing.scenes.interventionBody"),
      image: sceneInterventionImage,
    },
  ];

  const finalActions = [
    {
      to: "/simulations/new",
      label: t("landing.finalCta.new"),
      icon: SquarePlus,
      primary: true,
    },
    {
      to: "/dashboard",
      label: t("landing.finalCta.dashboard"),
      icon: LayoutDashboard,
      primary: false,
    },
    {
      to: "/simulations/saved",
      label: t("landing.finalCta.saved"),
      icon: Archive,
      primary: false,
    },
  ];

  return (
    <div className={`ss-landing ${themeClass}`.trim()}>
      <section className="ss-landing__hero ss-reveal">
        <div className="ss-landing__frame ss-landing__hero-grid">
          <div className="ss-landing__hero-copy">
            <div className="ss-landing__hero-stage">
              <div className="ss-landing__hero-body">
                <div className="ss-landing__headline-group">
                  <div className="ss-landing__title-stack">
                    <h1 className="ss-landing__title">
                      <span className="ss-landing__title-line">{t("landing.hero.line1")}</span>
                      <span className="ss-landing__title-line">{t("landing.hero.line2")}</span>
                      <span className="ss-landing__title-accent">{t("landing.hero.accent")}</span>
                    </h1>

                    <div className="ss-landing__eyebrow ss-landing__eyebrow--hero">
                      {t("landing.hero.badge")}
                    </div>
                  </div>

                  <p className="ss-landing__subtitle ss-landing__subtitle--dynamic">
                    {heroSubtitleSegments.map((segment) => (
                      <span key={segment} className="ss-landing__subtitle-segment">
                        {segment}
                      </span>
                    ))}
                  </p>
                </div>
              </div>

              <div className="ss-landing__hero-footer">
                <div className="ss-landing__hero-actions">
                  <Link to="/simulations/new" className="ss-landing__button ss-landing__button--primary">
                    <span>{t("landing.hero.primaryCta")}</span>
                    <ArrowRight size={16} />
                  </Link>
                  <Link to="/docs" className="ss-landing__button ss-landing__button--ghost">
                    {t("landing.hero.secondaryCta")}
                  </Link>
                </div>

                <div className="ss-landing__tag-row">
                  {heroTags.map((tag) => (
                    <span key={tag} className="ss-landing__tag">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <aside className="ss-landing__entry-board">
            <div className="ss-landing__entry-board-shell">
              <div className="ss-landing__entry-board-head">
                <span className="ss-landing__entry-board-kicker">{t("landing.entry.primaryBadge")}</span>
                <div className="ss-landing__entry-board-line" />
              </div>

              <Link to="/simulations/new" className="ss-landing__launch-card">
                <div className="ss-landing__launch-card-top">
                  <SquarePlus className="ss-landing__matrix-icon ss-landing__matrix-icon--primary" size={24} />
                  <span className="ss-landing__launch-route">/simulations/new</span>
                </div>

                <div className="ss-landing__matrix-copy">
                  <h2 className="ss-landing__matrix-title">{t("landing.entry.primaryTitle")}</h2>
                  <p className="ss-landing__matrix-subtitle">{t("landing.entry.primarySubtitle")}</p>
                </div>

                <div className="ss-landing__launch-card-bottom">
                  <span className="ss-landing__launch-pill">{t("landing.hero.primaryCta")}</span>
                  <ArrowRight size={16} />
                </div>
              </Link>

              <div className="ss-landing__entry-matrix">
                {entryCards.map((card) => {
                  const Icon = card.icon;

                  return (
                    <Link key={card.title} to={card.to} className="ss-landing__entry-tile">
                      <div className="ss-landing__entry-tile-top">
                        <Icon className="ss-landing__matrix-icon" size={20} />
                        <ArrowUpRight className="ss-landing__entry-arrow" size={15} />
                      </div>

                      <div className="ss-landing__matrix-copy">
                        <h3 className="ss-landing__matrix-title">{card.title}</h3>
                        <p className="ss-landing__matrix-subtitle">{card.subtitle}</p>
                      </div>

                      <span className="ss-landing__entry-path">{card.to}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
          </aside>
        </div>
      </section>

      <section className="ss-landing__preview-band ss-reveal">
        <div className="ss-landing__frame ss-landing__preview-shell">
          <div className="ss-landing__preview-head">
            <div className="ss-landing__preview-copy">
              <h2 className="ss-landing__section-title">
                {t("landing.preview.title")}
                <span className="ss-landing__section-title-accent">{t("landing.preview.accent")}</span>
              </h2>
              <p className="ss-landing__section-subtitle">{t("landing.preview.sub")}</p>
            </div>

            <Link to="/simulations/new" className="ss-landing__preview-link">
              <span>{t("landing.preview.cta")}</span>
              <ArrowUpRight className="ss-landing__preview-link-icon" size={16} />
            </Link>
          </div>

          <div className="ss-landing__preview-grid">
            <div
              ref={previewStageRef}
              className="ss-landing__preview-stage ss-landing__preview-stage--video"
            >
              {hasExternalPreview && isPreviewActive ? (
                <iframe
                  className="ss-landing__preview-video"
                  src={getBilibiliEmbedUrl()}
                  scrolling="no"
                  frameBorder="0"
                  allowFullScreen
                  title={String(t("landing.preview.title"))}
                />
              ) : hasExternalPreview ? (
                <button
                  type="button"
                  className="ss-landing__button ss-landing__button--primary ss-landing__preview-activator"
                  onClick={() => setIsPreviewActive(true)}
                >
                  <span>{t("landing.preview.cta")}</span>
                  <ArrowRight size={16} />
                </button>
              ) : (
                <video
                  className="ss-landing__preview-video"
                  autoPlay
                  loop
                  muted
                  playsInline
                  preload="metadata"
                  aria-label={String(t("landing.preview.title"))}
                />
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="ss-landing__capabilities ss-reveal">
        <div className="ss-landing__frame">
          <div className="ss-landing__capability-head">
            <h2 className="ss-landing__section-title ss-landing__section-title--center">
              {t("landing.capabilities.title")}
            </h2>
            <div className="ss-landing__divider" />
          </div>

          <div className="ss-landing__capability-grid">
            <article className="ss-landing__capability-card ss-landing__capability-card--large">
              <div className="ss-landing__capability-copy">
                <Waypoints className="ss-landing__capability-icon" size={38} />
                <div>
                  <h3 className="ss-landing__capability-title">{t("landing.capabilities.designTitle")}</h3>
                  <p className="ss-landing__capability-subtitle">{t("landing.capabilities.designSubtitle")}</p>
                </div>
                <p className="ss-landing__capability-body">{t("landing.capabilities.designBody")}</p>
              </div>

              <div className="ss-landing__capability-media">
                <img
                  src={experimentDesignImage}
                  alt="FOS experiment design interface"
                  className="ss-landing__capability-image"
                  loading="lazy"
                  decoding="async"
                  fetchPriority="low"
                />
              </div>
            </article>

            <article className="ss-landing__capability-card ss-landing__capability-card--small">
              <div className="ss-landing__capability-small-top">
                <Eye className="ss-landing__capability-icon ss-landing__capability-icon--accent" size={24} />
                <div>
                  <h3 className="ss-landing__capability-title">{t("landing.capabilities.observeTitle")}</h3>
                  <p className="ss-landing__capability-subtitle">{t("landing.capabilities.observeSubtitle")}</p>
                </div>
              </div>
              <div className="ss-landing__capability-thumb">
                <img
                  src={realtimeObservationImage}
                  alt="Real-time simulation observation interface"
                  className="ss-landing__capability-thumb-img"
                  loading="lazy"
                  decoding="async"
                  fetchPriority="low"
                />
              </div>
            </article>

            <article className="ss-landing__capability-card ss-landing__capability-card--small">
              <div className="ss-landing__capability-small-top">
                <GitBranch className="ss-landing__capability-icon" size={24} />
                <div>
                  <h3 className="ss-landing__capability-title">{t("landing.capabilities.branchTitle")}</h3>
                  <p className="ss-landing__capability-subtitle">{t("landing.capabilities.branchSubtitle")}</p>
                </div>
              </div>
              <div className="ss-landing__capability-thumb">
                <img
                  src={networkTopologyImage}
                  alt="Branch and compare simulation timelines"
                  className="ss-landing__capability-thumb-img"
                  loading="lazy"
                  decoding="async"
                  fetchPriority="low"
                />
              </div>
            </article>

            <Link to="/simulations/new" className="ss-landing__capability-banner">
              <div>
                <h3 className="ss-landing__capability-banner-title">{t("landing.capabilities.controlTitle")}</h3>
                <p className="ss-landing__capability-banner-copy">{t("landing.capabilities.controlBody")}</p>
              </div>
              <SlidersHorizontal className="ss-landing__capability-banner-icon" size={42} />
            </Link>
          </div>
        </div>
      </section>

      <section className="ss-landing__scenes ss-reveal">
        <div className="ss-landing__frame">
          <div className="ss-landing__scene-head">
            <h2 className="ss-landing__section-title">{t("landing.scenes.title")}</h2>
            <p className="ss-landing__scene-kicker">{t("landing.scenes.kicker")}</p>
          </div>

          <div className="ss-landing__scene-grid">
            {sceneCards.map((card) => (
              <article
                key={card.title}
                className={`ss-landing__scene-card ss-landing__scene-card--${card.tone}`}
              >
                <div className="ss-landing__scene-img-wrap">
                  <img
                    src={card.image}
                    alt={card.title}
                    className="ss-landing__scene-img"
                    loading="lazy"
                    decoding="async"
                    fetchPriority="low"
                  />
                </div>
                <div className="ss-landing__scene-content">
                  <h3 className="ss-landing__scene-title">
                    {card.title}
                    <span className="ss-landing__scene-subtitle">{card.subtitle}</span>
                  </h3>
                  <div className="ss-landing__scene-line" />
                  <p className="ss-landing__scene-body">{card.body}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="ss-landing__final ss-reveal">
        <div className="ss-landing__frame">
          <div className="ss-landing__final-panel">
            <div className="ss-landing__final-copy">
              <h2 className="ss-landing__section-title ss-landing__section-title--center">
                {t("landing.finalCta.title")}
              </h2>
              <p className="ss-landing__section-subtitle ss-landing__section-subtitle--center">
                {t("landing.finalCta.sub")}
              </p>
            </div>

            <div className="ss-landing__decision-grid">
              {finalActions.map((action, index) => {
                const Icon = action.icon;

                return (
                  <Link
                    key={action.label}
                    to={action.to}
                    className={`ss-landing__decision-card ${
                      action.primary ? "ss-landing__final-button--primary" : ""
                    }`}
                  >
                    <div className="ss-landing__decision-top">
                      <Icon className="ss-landing__final-button-icon" size={18} />
                      <span className="ss-landing__decision-index">{String(index + 1).padStart(2, "0")}</span>
                    </div>
                    <div className="ss-landing__decision-copy">
                      <span className="ss-landing__decision-label">{action.label}</span>
                      <span className="ss-landing__decision-path">{action.to}</span>
                    </div>
                    <ArrowRight className="ss-landing__decision-arrow" size={18} />
                  </Link>
                );
              })}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
