/**
 * This file starts the website after translations are ready.
 *
 * It creates the shared query cache, applies the configured base path, and mounts App.
 */

import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import "./styles.css";
import { initializeI18n } from "./i18n";

const rawBaseUrl = import.meta.env.BASE_URL;
const basename =
  rawBaseUrl === "/"
    ? ""
    : rawBaseUrl.length > 1 && rawBaseUrl.endsWith("/")
      ? rawBaseUrl.slice(0, -1)
      : rawBaseUrl;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    },
  },
});

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Could not find root element to mount to");
}

const tree = (
  <QueryClientProvider client={queryClient}>
    <BrowserRouter basename={basename}>
      <App />
    </BrowserRouter>
  </QueryClientProvider>
);

// 开发环境不套 StrictMode，生产环境再套
initializeI18n()
  .then(() => {
    ReactDOM.createRoot(rootElement).render(tree);
  })
  .catch((error: unknown) => {
    console.error("Failed to start translations", error);
    throw error;
  });
