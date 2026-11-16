/**
 * This file connects website addresses to the pages people see.
 *
 * App applies the theme and keeps the shared page shell visible while each page downloads.
 * RouteContent shows loading and recovery UI, while ProtectedProductPage also checks login.
 */

import React, { Suspense, useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { Layout } from "./components/Layout";
import { RequireAuth } from "./components/RequireAuth";
import { RouteLoading } from "./components/RouteLoading";
import { AuthLayout } from "./components/layout/AuthLayout";
import {
  AdminPage,
  CreateExperimentCustomPage,
  CreateExperimentPage,
  CreateExperimentPresetPage,
  DashboardPage,
  DocsPage,
  LandingPage,
  LoginPage,
  RegisterPage,
  ReleaseDemoPage,
  SavedSimulationsPage,
  SettingsPage,
  SimulationPage,
  prefetchCommonRoutes,
} from "./routes/lazyRoutes";
import { useSimulationStore } from "./store";
import { useThemeStore } from "./store/theme";

function RouteContent({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <Suspense fallback={<RouteLoading />}>{children}</Suspense>
    </ErrorBoundary>
  );
}

function ProductPage({ children }: { children: React.ReactNode }) {
  return (
    <Layout navVariant="product">
      <RouteContent>{children}</RouteContent>
    </Layout>
  );
}

function ProtectedProductPage({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <ProductPage>{children}</ProductPage>
    </RequireAuth>
  );
}

const App: React.FC = () => {
  const applyTheme = useThemeStore((state) => state.apply);
  const currentSimulationId = useSimulationStore((state) => state.currentSimulation?.id ?? null);

  useEffect(() => {
    applyTheme();
  }, [applyTheme]);

  useEffect(() => {
    const startPrefetch = () => prefetchCommonRoutes();
    if ("requestIdleCallback" in window) {
      const idleId = window.requestIdleCallback(startPrefetch, { timeout: 2500 });
      return () => window.cancelIdleCallback(idleId);
    }
    const timerId = globalThis.setTimeout(startPrefetch, 1000);
    return () => globalThis.clearTimeout(timerId);
  }, []);

  return (
    <Routes>
      <Route path="/" element={<ProductPage><LandingPage /></ProductPage>} />
      <Route path="/login" element={<AuthLayout><RouteContent><LoginPage /></RouteContent></AuthLayout>} />
      <Route path="/register" element={<AuthLayout><RouteContent><RegisterPage /></RouteContent></AuthLayout>} />
      <Route path="/dashboard" element={<ProtectedProductPage><DashboardPage /></ProtectedProductPage>} />
      <Route path="/docs/*" element={<ProductPage><DocsPage /></ProductPage>} />
      <Route path="/meeting" element={<ProductPage><ReleaseDemoPage /></ProductPage>} />
      <Route
        path="/simulations/create"
        element={<ProtectedProductPage><CreateExperimentPage /></ProtectedProductPage>}
      />
      <Route
        path="/simulations/create/preset"
        element={<ProtectedProductPage><CreateExperimentPresetPage /></ProtectedProductPage>}
      />
      <Route
        path="/simulations/create/custom"
        element={<ProtectedProductPage><CreateExperimentCustomPage /></ProtectedProductPage>}
      />
      <Route
        path="/simulations/new/*"
        element={<ProtectedProductPage><CreateExperimentPage /></ProtectedProductPage>}
      />
      <Route
        path="/simulations/workspace"
        element={
          <ProtectedProductPage>
            {currentSimulationId
              ? <Navigate to={`/simulations/${currentSimulationId}`} replace />
              : <SimulationPage />}
          </ProtectedProductPage>
        }
      />
      <Route
        path="/simulations/saved"
        element={<ProtectedProductPage><SavedSimulationsPage /></ProtectedProductPage>}
      />
      <Route
        path="/simulations/:id"
        element={<ProtectedProductPage><SimulationPage /></ProtectedProductPage>}
      />
      <Route
        path="/settings/*"
        element={<ProtectedProductPage><SettingsPage /></ProtectedProductPage>}
      />
      <Route
        path="/admin"
        element={
          <RequireAuth>
            <Layout><RouteContent><AdminPage /></RouteContent></Layout>
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export default App;
