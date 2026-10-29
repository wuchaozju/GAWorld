import { ArrowRight, MoonStar, SunMedium } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { LanguageSwitcher } from "../LanguageSwitcher";
import { BrandLogo } from "../BrandLogo";
import { useThemeStore } from "../../store/theme";

export function AuthLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const mode = useThemeStore((state) => state.mode);
  const toggle = useThemeStore((state) => state.toggle);
  const themeClass = mode === "dark" ? "is-dark" : "is-light";
  const themeToggleLabel =
    mode === "dark"
      ? t("a11y.switchToLight")
      : t("a11y.switchToDark");
  const heroTags = [
    t("landing.hero.tag1"),
    t("landing.hero.tag2"),
    t("landing.hero.tag3"),
  ];

  return (
    <div className={`ss-auth ${themeClass}`.trim()}>
      <div className="ss-auth-shell">
        <header className="ss-auth__topbar">
          <Link to="/" className="ss-auth__topbar-brand">
            <BrandLogo layout="stacked" />
          </Link>

          <nav className="ss-auth__topbar-nav" aria-label={t("a11y.primaryNav")}>
            <Link to="/simulations/new">{t("auth.layout.exhibits")}</Link>
            <Link to="/simulations/saved">{t("auth.layout.journals")}</Link>
            <Link to="/docs">{t("auth.layout.index")}</Link>
          </nav>

          <div className="ss-auth__topbar-controls">
            <button
              type="button"
              className="ss-auth__utility-button"
              onClick={toggle}
              aria-label={themeToggleLabel}
              title={themeToggleLabel}
            >
              {mode === "dark" ? <SunMedium size={16} /> : <MoonStar size={16} />}
            </button>
            <LanguageSwitcher variant="product" />
          </div>
        </header>

        <section className="ss-auth__hero">
          <div className="ss-auth__hero-grid" />
          <div className="ss-auth__hero-content">
            <div className="ss-auth__hero-frame">
              <div className="ss-auth__hero-surface">
                <div className="ss-auth__hero-badge">
                  <span className="ss-auth__hero-badge-dot" />
                  {t("landing.hero.badge")}
                </div>

                <div className="ss-auth__hero-main">
                  <h1 className="ss-auth__hero-display">{t("landing.hero.line1")}</h1>
                  <p className="ss-auth__hero-accent">{t("landing.hero.accent")}</p>
                  <p className="ss-auth__hero-copy">{t("landing.hero.sub")}</p>
                </div>

                <div className="ss-auth__hero-actions">
                  <Link to="/simulations/new" className="ss-auth__hero-action ss-auth__hero-action--primary">
                    <span>{t("landing.hero.primaryCta")}</span>
                    <ArrowRight size={16} />
                  </Link>
                  <Link to="/docs" className="ss-auth__hero-action ss-auth__hero-action--ghost">
                    {t("landing.hero.secondaryCta")}
                  </Link>
                </div>

                <div className="ss-auth__hero-tags">
                  {heroTags.map((tag) => (
                    <span key={tag} className="ss-auth__hero-tag">{tag}</span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="ss-auth__panel">
          <div className="ss-auth__panel-shell">{children}</div>
        </section>
      </div>
    </div>
  );
}
