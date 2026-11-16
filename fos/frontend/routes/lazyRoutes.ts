/**
 * This file lists pages that are downloaded only when people need them.
 *
 * Each page retries temporary download failures, and prefetchRoute starts likely downloads early.
 */

import type { ComponentType } from "react";

import { lazyWithRetry, loadWithRetry } from "../utils/lazyWithRetry";

type PageComponent = ComponentType<Record<string, never>>;
type PageModule = { default: PageComponent };

function namedPage(
  importer: () => Promise<Record<string, unknown>>,
  exportName: string,
): () => Promise<PageModule> {
  return async () => {
    const module = await importer();
    return { default: module[exportName] as PageComponent };
  };
}

const dashboardImport = namedPage(() => import("../pages/DashboardPage"), "DashboardPage");
const landingImport = namedPage(() => import("../pages/LandingPage"), "LandingPage");
const loginImport = namedPage(() => import("../pages/LoginPage"), "LoginPage");
const registerImport = namedPage(() => import("../pages/RegisterPage"), "RegisterPage");
const savedImport = namedPage(() => import("../pages/SavedSimulationsPage"), "SavedSimulationsPage");
const settingsImport = namedPage(() => import("../pages/SettingsPage"), "SettingsPage");
const adminImport = namedPage(() => import("../pages/AdminPage"), "AdminPage");
const createImport = namedPage(() => import("../pages/CreateExperimentPage"), "CreateExperimentPage");
const presetImport = namedPage(
  () => import("../pages/CreateExperimentPresetPage"),
  "CreateExperimentPresetPage",
);
const customImport = namedPage(
  () => import("../pages/CreateExperimentCustomPage"),
  "CreateExperimentCustomPage",
);
const docsImport = namedPage(() => import("../pages/DocsPage"), "DocsPage");
const releaseImport = namedPage(() => import("../pages/ReleaseDemoPage"), "ReleaseDemoPage");
const simulationImport = () => import("../pages/SimulationPage");

export const DashboardPage = lazyWithRetry(dashboardImport, "dashboard");
export const LandingPage = lazyWithRetry(landingImport, "landing");
export const LoginPage = lazyWithRetry(loginImport, "login");
export const RegisterPage = lazyWithRetry(registerImport, "register");
export const SavedSimulationsPage = lazyWithRetry(savedImport, "saved-simulations");
export const SettingsPage = lazyWithRetry(settingsImport, "settings");
export const AdminPage = lazyWithRetry(adminImport, "admin");
export const CreateExperimentPage = lazyWithRetry(createImport, "create-experiment");
export const CreateExperimentPresetPage = lazyWithRetry(presetImport, "create-preset");
export const CreateExperimentCustomPage = lazyWithRetry(customImport, "create-custom");
export const DocsPage = lazyWithRetry(docsImport, "docs");
export const ReleaseDemoPage = lazyWithRetry(releaseImport, "release-demo");
export const SimulationPage = lazyWithRetry(simulationImport, "simulation");

const routeImports: Record<string, { importer: () => Promise<unknown>; name: string }> = {
  "/dashboard": { importer: dashboardImport, name: "dashboard" },
  "/simulations/new": { importer: createImport, name: "create-experiment" },
  "/simulations/create": { importer: createImport, name: "create-experiment" },
  "/simulations/create/preset": { importer: presetImport, name: "create-preset" },
  "/simulations/create/custom": { importer: customImport, name: "create-custom" },
  "/simulations/saved": { importer: savedImport, name: "saved-simulations" },
  "/settings/providers": { importer: settingsImport, name: "settings" },
  "/docs": { importer: docsImport, name: "docs" },
};

export function prefetchRoute(path: string): void {
  const route = routeImports[path];
  if (!route) return;

  void loadWithRetry(route.importer, route.name).catch((error: unknown) => {
    console.warn(`Could not prefetch ${path}`, error);
  });
}

export function prefetchCommonRoutes(): void {
  prefetchRoute("/simulations/new");
  prefetchRoute("/settings/providers");
}
