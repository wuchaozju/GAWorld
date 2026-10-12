/**
 * This file protects pages that need a signed-in person.
 *
 * RequireAuth restores saved login details, shows a loading message while it works,
 * and sends signed-out visitors to the login page.
 *
 * In single-user mode (exposed by the unauthenticated /config endpoint) the
 * login redirect is skipped: the app opens directly with the backend's local
 * user. When single-user mode is off, the normal login flow is unchanged.
 */

import { type ReactNode, useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { RouteLoading } from "./RouteLoading";
import { useAuthStore } from "../store/auth";
import { getApiBase } from "../services/base";

type Props = {
  children: ReactNode;
};

export function RequireAuth({ children }: Props) {
  const location = useLocation();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const checkSession = useAuthStore((state) => state.restoreSession);
  const hasRestored = useAuthStore((state) => state.hasRestored);

  // null = still querying; true/false = server answer.
  const [singleUserMode, setSingleUserMode] = useState<boolean | null>(null);

  useEffect(() => {
    if (!hasRestored) {
      checkSession();
    }
  }, [checkSession, hasRestored]);

  useEffect(() => {
    if (!hasRestored || isAuthenticated || singleUserMode !== null) {
      return;
    }
    let cancelled = false;
    fetch(`${getApiBase()}/config`)
      .then((res) => (res.ok ? res.json() : {}))
      .then((cfg: { single_user_mode?: boolean }) => {
        if (!cancelled) setSingleUserMode(Boolean(cfg.single_user_mode));
      })
      .catch(() => {
        if (!cancelled) setSingleUserMode(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hasRestored, isAuthenticated, singleUserMode]);

  if (!hasRestored) {
    return <RouteLoading />;
  }

  if (!isAuthenticated) {
    // Single-user mode: skip the login redirect entirely.
    if (singleUserMode === null) {
      return <RouteLoading />;
    }
    if (!singleUserMode) {
      return <Navigate to="/login" replace state={{ from: location }} />;
    }
  }

  return <>{children}</>;
}
