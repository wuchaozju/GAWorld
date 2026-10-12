/**
 * This file protects pages that need a signed-in person.
 *
 * RequireAuth restores saved login details, shows a loading message while it works,
 * and sends signed-out visitors to the login page.
 */

import { type ReactNode, useEffect } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { RouteLoading } from "./RouteLoading";
import { useAuthStore } from "../store/auth";

type Props = {
  children: ReactNode;
};

export function RequireAuth({ children }: Props) {
  const location = useLocation();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const checkSession = useAuthStore((state) => state.restoreSession);
  const hasRestored = useAuthStore((state) => state.hasRestored);

  useEffect(() => {
    if (!hasRestored) {
      checkSession();
    }
  }, [checkSession, hasRestored]);

  if (!hasRestored) {
    return <RouteLoading />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <>{children}</>;
}
