/**
 * This file checks that a page download is tried again after a temporary failure.
 *
 * The test makes sure lazyWithRetry retries once and returns the page when the second try works.
 */

import { describe, expect, it, vi } from "vitest";

import { loadWithRetry } from "./lazyWithRetry";

describe("loadWithRetry", () => {
  it("tries a failed page download one more time", async () => {
    const pageModule = { default: () => null };
    const importer = vi
      .fn<() => Promise<typeof pageModule>>()
      .mockRejectedValueOnce(new TypeError("Failed to fetch dynamically imported module"))
      .mockResolvedValueOnce(pageModule);

    await expect(loadWithRetry(importer, "settings")).resolves.toBe(pageModule);
    expect(importer).toHaveBeenCalledTimes(2);
  });
});
