/*
This file checks that the app builder knows what "@/" means.
The test makes sure the Vite config points "@" at the frontend folder so imports like "@/store" can load.
*/

// @vitest-environment node

import { describe, expect, it } from "vitest";
import path from "path";
import viteConfig, { createPwaOptions } from "./vite.config";

describe("vite config", () => {
  it("maps at-imports to the frontend folder", () => {
    const config = viteConfig({ mode: "test", command: "serve", isSsrBuild: false, isPreview: false });

    expect(config.resolve?.alias).toEqual({
      "@": path.resolve(__dirname, "./"),
    });
  });

  it("keeps service worker files under the configured website path", () => {
    process.env.FRONTEND_BASE_URL = "/css/fos/";
    const config = viteConfig({ mode: "test", command: "build", isSsrBuild: false, isPreview: false });
    const pwaOptions = createPwaOptions("/css/fos/");

    expect(config.base).toBe("/css/fos/");
    expect(pwaOptions).toMatchObject({
      base: "/css/fos/",
      scope: "/css/fos/",
      manifest: {
        start_url: "/css/fos/",
        scope: "/css/fos/",
        icons: [{ src: "/css/fos/assets/favicon.png" }],
      },
    });
    expect(pwaOptions.workbox?.globPatterns).not.toContain("**/*.svg");
    expect(pwaOptions.workbox?.runtimeCaching).toEqual(
      expect.not.arrayContaining([
        expect.objectContaining({ cacheName: "api-cache" }),
      ]),
    );
    delete process.env.FRONTEND_BASE_URL;
  });
});
