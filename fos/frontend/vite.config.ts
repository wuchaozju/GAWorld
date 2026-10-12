/**
 * This file tells the frontend builder how to serve, split, and cache the website.
 *
 * virtualDocsPlugin supplies the built-in help page.
 * normalizeBase keeps the website path consistent.
 * createPwaOptions keeps offline files inside that website path.
 * manualChunkName groups shared libraries without pulling unrelated pages together.
 */

import path from "path";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";
import type { VitePWAOptions } from "vite-plugin-pwa";

function virtualDocsPlugin(): Plugin {
  return {
    name: "virtual-docs",
    resolveId(id) {
      if (id === "virtual:docs") return "\0virtual:docs";
      return undefined;
    },
    load(id) {
      if (id !== "\0virtual:docs") return undefined;
      return `
        const docs = {
          sections: [{
            id: "overview",
            title: "FOS documentation",
            lang: "en",
            html: "<h1>FOS documentation</h1><p>The built-in documentation module is ready.</p>"
          }]
        };
        export default docs;
      `;
    },
  };
}

function normalizeBase(value: string): string {
  const withLeadingSlash = value.startsWith("/") ? value : `/${value}`;
  return withLeadingSlash.endsWith("/") ? withLeadingSlash : `${withLeadingSlash}/`;
}

export function createPwaOptions(baseValue: string): Partial<VitePWAOptions> {
  const base = normalizeBase(baseValue);
  return {
    base,
    scope: base,
    registerType: "autoUpdate",
    workbox: {
      globPatterns: ["**/*.{js,css,html,ico,woff,woff2,json,png}"],
      navigateFallback: `${base}index.html`,
      runtimeCaching: [
        {
          urlPattern: /^https:\/\/fonts\.googleapis\.com\/.*/i,
          handler: "CacheFirst",
          options: {
            cacheName: "google-fonts-stylesheets",
            expiration: { maxEntries: 4, maxAgeSeconds: 60 * 60 * 24 * 365 },
          },
        },
        {
          urlPattern: /^https:\/\/fonts\.gstatic\.com\/.*/i,
          handler: "CacheFirst",
          options: {
            cacheName: "google-fonts-files",
            expiration: { maxEntries: 20, maxAgeSeconds: 60 * 60 * 24 * 365 },
          },
        },
      ],
    },
    manifest: {
      name: "FOS - Social Simulation Platform",
      short_name: "FOS",
      description: "Architecting social logic for branching, observation, and intervention",
      theme_color: "#1a1a2e",
      background_color: "#ffffff",
      display: "standalone",
      start_url: base,
      scope: base,
      icons: [{ src: `${base}assets/favicon.png`, sizes: "64x64", type: "image/png" }],
    },
  };
}

function manualChunkName(id: string): string | undefined {
  if (!id.includes("node_modules")) return undefined;
  if (
    id.includes("reactflow") ||
    id.includes("@react-sigma") ||
    id.includes("graphology") ||
    id.includes("dagre") ||
    /[\\/]node_modules[\\/](d3|sigma)[\\/]/.test(id)
  ) {
    return "graph-vendor";
  }
  if (id.includes("recharts")) return "charts-vendor";
  if (
    id.includes("react-markdown") ||
    id.includes("@mdx-js") ||
    id.includes("micromark") ||
    id.includes("remark") ||
    id.includes("unified")
  ) {
    return "markdown-vendor";
  }
  if (id.includes("@radix-ui")) return "radix-vendor";
  if (id.includes("@tanstack") || id.includes("axios")) return "data-vendor";
  if (id.includes("i18next") || id.includes("react-i18next")) return "i18n-vendor";
  if (id.includes("lucide-react")) return "icons-vendor";
  if (/[\\/]node_modules[\\/](react|react-dom|react-router|react-router-dom|scheduler)[\\/]/.test(id)) {
    return "react-vendor";
  }
  return undefined;
}

const optimizeDepsInclude = [
  "react",
  "react-dom",
  "react-dom/client",
  "react-router-dom",
  "scheduler",
  "@tanstack/react-query",
  "@tanstack/react-virtual",
  "axios",
  "i18next",
  "react-i18next",
  "zustand",
  "zustand/middleware",
  "zustand/react/shallow",
  "lucide-react",
  "@radix-ui/react-dropdown-menu",
  "@radix-ui/react-select",
  "@radix-ui/react-icons",
  "@google/genai",
  "uuid",
  "zod",
  "seedrandom",
  "papaparse",
  "d3",
  "dagre",
  "graphology",
  "graphology-layout-forceatlas2",
  "@react-sigma/core",
  "@sigma/node-image",
  "sigma",
  "sigma/rendering",
  "reactflow",
  "recharts",
  "react-markdown",
  "rehype-raw",
  "@mdx-js/react",
];

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const host = env.LISTEN_ADDRESS || "0.0.0.0";
  const port = Number(env.LISTEN_PORT || 5173);
  const backendPort = Number(env.BACKEND_PORT || 8000);
  const base = normalizeBase(env.FRONTEND_BASE_URL || "/");

  return {
    base,
    plugins: [
      react(),
      virtualDocsPlugin(),
    ],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./"),
      },
    },
    optimizeDeps: {
      include: optimizeDepsInclude,
    },
    assetsInclude: ["**/*.md"],
    server: {
      host,
      port,
      proxy: {
        "/api": {
          target: `http://127.0.0.1:${backendPort}`,
          changeOrigin: true,
        },
        "/uploads": {
          target: `http://127.0.0.1:${backendPort}`,
          changeOrigin: true,
        },
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: manualChunkName,
        },
      },
    },
  };
});
