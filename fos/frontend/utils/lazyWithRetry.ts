/**
 * This file downloads page code and gives temporary download failures one more chance.
 *
 * loadWithRetry retries an import once and refreshes once when an old deployment points at missing files.
 * lazyWithRetry turns that behavior into a React lazy component.
 */

import { lazy, type ComponentType, type LazyExoticComponent } from "react";

const RETRY_DELAY_MS = 150;
const RELOAD_MARKER_PREFIX = "fos.lazy-reload:";

function isChunkLoadError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const message = error.message.toLowerCase();
  return (
    message.includes("failed to fetch dynamically imported module") ||
    message.includes("loading chunk") ||
    message.includes("chunkloaderror") ||
    message.includes("importing a module script failed")
  );
}

function waitBeforeRetry(): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, RETRY_DELAY_MS);
  });
}

function reloadOnceForStaleChunk(chunkName: string, error: unknown): never {
  if (typeof window === "undefined" || !isChunkLoadError(error)) {
    throw error;
  }

  const marker = `${RELOAD_MARKER_PREFIX}${chunkName}`;
  if (window.sessionStorage.getItem(marker) === "1") {
    window.sessionStorage.removeItem(marker);
    throw error;
  }

  window.sessionStorage.setItem(marker, "1");
  window.location.reload();
  throw error;
}

export async function loadWithRetry<T>(
  importer: () => Promise<T>,
  chunkName: string,
): Promise<T> {
  try {
    const module = await importer();
    window.sessionStorage.removeItem(`${RELOAD_MARKER_PREFIX}${chunkName}`);
    return module;
  } catch {
    await waitBeforeRetry();
  }

  try {
    const module = await importer();
    window.sessionStorage.removeItem(`${RELOAD_MARKER_PREFIX}${chunkName}`);
    return module;
  } catch (error: unknown) {
    return reloadOnceForStaleChunk(chunkName, error);
  }
}

export function lazyWithRetry<T extends ComponentType<Record<string, never>>>(
  importer: () => Promise<{ default: T }>,
  chunkName: string,
): LazyExoticComponent<T> {
  return lazy(() => loadWithRetry(importer, chunkName));
}
