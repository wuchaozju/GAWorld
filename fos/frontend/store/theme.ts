import { create } from "zustand";

export type ThemeMode = "light" | "dark";

type ThemeState = {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
  toggle: () => void;
  apply: () => void;
};

const STORAGE_KEY = "fos.theme";

function readInitialTheme(): ThemeMode {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  const prefersDark = typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  return prefersDark ? "dark" : "light";
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  mode: readInitialTheme(),
  setMode: (mode) => {
    localStorage.setItem(STORAGE_KEY, mode);
    set({ mode });
    get().apply();
  },
  toggle: () => {
    const next = get().mode === "dark" ? "light" : "dark";
    localStorage.setItem(STORAGE_KEY, next);
    set({ mode: next });
    get().apply();
  },
  apply: () => {
    const mode = get().mode;
    const root = document.documentElement;
    root.classList.remove("theme-light", "theme-dark");
    root.classList.add(mode === "dark" ? "theme-dark" : "theme-light");
  },
}));

