/**
 * This file shows the main website navigation on large and small screens.
 *
 * NavBar marks the current page, opens the mobile menu, changes theme and language,
 * handles sign-out, and starts downloading destination pages when links are focused.
 */

import { useEffect, useState } from "react";
import { Menu, MoonStar, SunMedium, X } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { useAuthStore } from "../store/auth";
import { useThemeStore } from "../store/theme";
import { prefetchRoute } from "../routes/lazyRoutes";

const DESKTOP_BREAKPOINT_QUERY = "(min-width: 961px)";

export type NavBarVariant = "default" | "product";

export function NavBar({ variant = "default" }: { variant?: NavBarVariant }) {
  const location = useLocation();
  const { t } = useTranslation();
  const [compactOpen, setCompactOpen] = useState(false);

  const user = useAuthStore((s) => s.user);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const clearSession = useAuthStore((s) => s.clearSession);

  const mode = useThemeStore((s) => s.mode);
  const toggle = useThemeStore((s) => s.toggle);

  const isProduct = variant === "product";
  const isAdmin = String(user?.role ?? "") === "admin";
  const navItems = [
    { to: "/dashboard", label: t("nav.dashboard") },
    { to: "/simulations/new", label: t("nav.new") },
    { to: "/simulations/saved", label: t("nav.saved") },
    { to: "/settings/providers", label: t("nav.settings") },
    { to: "/docs", label: t("nav.docs") || "Docs" },
  ];
  const allNavItems = isAdmin
    ? [...navItems, { to: "/admin", label: t("nav.admin") || "Admin" }]
    : navItems;
  const themeIcon =
    isProduct
      ? mode === "dark"
        ? <MoonStar size={16} strokeWidth={2.1} />
        : <SunMedium size={16} strokeWidth={2.1} />
      : mode === "dark"
        ? "🌙"
        : "☀️";

  useEffect(() => {
    setCompactOpen(false);
  }, [location.pathname, variant]);

  useEffect(() => {
    if (!isProduct) {
      return;
    }

    const media = window.matchMedia(DESKTOP_BREAKPOINT_QUERY);
    const closeCompact = () => {
      if (media.matches) {
        setCompactOpen(false);
      }
    };

    closeCompact();
    media.addEventListener("change", closeCompact);

    return () => media.removeEventListener("change", closeCompact);
  }, [isProduct]);

  const renderNavLinks = (extraClass = "") =>
    allNavItems.map((item) => (
      <Link
        key={item.to}
        to={item.to}
        onMouseEnter={() => prefetchRoute(item.to)}
        onFocus={() => prefetchRoute(item.to)}
        className={`nav-link ${extraClass} ${
          location.pathname.startsWith(item.to) ? "active" : ""
        }`.trim()}
      >
        {item.label}
      </Link>
    ));

  return (
    <nav className={`nav ${isProduct ? "nav--product" : ""} ${compactOpen ? "nav--product-open" : ""}`}>
      <div className="nav-shell">
        <div className="nav-left">
          <Link to="/" className="nav-brand">
            {t("brand")}
          </Link>

          <div className="nav-links nav-links--desktop">
            {renderNavLinks()}
          </div>
        </div>

        <div className="nav-right">
          <div className="nav-utilities">
            <button
              type="button"
              className={`icon-button ${isProduct ? "icon-button--product square" : ""}`}
              onClick={toggle}
              title={t("components.navBar.toggleTheme")}
            >
              {themeIcon}
            </button>

            <LanguageSwitcher variant={isProduct ? "product" : "default"} />
          </div>

          {isProduct ? <div className="nav-divider nav-divider--desktop" /> : null}

          <div className={`nav-session ${isProduct ? "nav-session--desktop" : ""}`}>
            {isAuthenticated ? (
              <div className={`nav-user ${isProduct ? "nav-user--product" : ""}`}>
                <span className="nav-username">
                  {String(user?.email ?? "")}
                </span>
                <button
                  type="button"
                  className={`text-button ${isProduct ? "nav-signout" : ""}`}
                  onClick={clearSession}
                >
                  {t("nav.signout")}
                </button>
              </div>
            ) : (
              <div className={`nav-auth ${isProduct ? "nav-auth--product" : ""}`}>
                <Link
                  to="/login"
                  className={isProduct ? "nav-auth-link nav-auth-link--login" : "nav-link"}
                >
                  {t("nav.login")}
                </Link>
                <Link
                  to="/register"
                  className={isProduct ? "nav-auth-link nav-auth-link--register" : "nav-link"}
                >
                  {t("nav.register")}
                </Link>
              </div>
            )}
          </div>

          {isProduct ? (
            <button
              type="button"
              className="icon-button icon-button--product square nav-menu-toggle"
              onClick={() => setCompactOpen((open) => !open)}
              aria-expanded={compactOpen}
              aria-controls="product-nav-panel"
              aria-label={compactOpen ? t("common.hide") : t("common.show")}
              title={compactOpen ? t("common.hide") : t("common.show")}
            >
              {compactOpen ? <X size={17} strokeWidth={2.1} /> : <Menu size={17} strokeWidth={2.1} />}
            </button>
          ) : null}
        </div>
      </div>

      {isProduct ? (
        <div
          id="product-nav-panel"
          className={`nav-mobile ${compactOpen ? "nav-mobile--open" : ""}`}
          aria-hidden={!compactOpen}
        >
          <div className="nav-mobile-shell">
            <div className="nav-mobile-links">{renderNavLinks("nav-link--mobile")}</div>

            {isAuthenticated ? (
              <div className="nav-mobile-session nav-mobile-session--user">
                <span className="nav-mobile-email">{String(user?.email ?? "")}</span>
                <button type="button" className="nav-mobile-signout" onClick={clearSession}>
                  {t("nav.signout")}
                </button>
              </div>
            ) : (
              <div className="nav-mobile-session">
                <Link to="/login" className="nav-auth-link nav-auth-link--login">
                  {t("nav.login")}
                </Link>
                <Link to="/register" className="nav-auth-link nav-auth-link--register">
                  {t("nav.register")}
                </Link>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </nav>
  );
}
