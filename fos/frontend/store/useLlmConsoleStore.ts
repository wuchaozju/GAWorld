// frontend/store/useLlmConsoleStore.ts
// 专用于LLM控制台的Zustand store
import { create } from "zustand";
import { devtools } from "zustand/middleware";
import { createLlmConsoleSlice, type LlmConsoleState } from "./llmConsoleSlice";

export const useLlmConsoleStore = create<LlmConsoleState>()(
  devtools(
    (set, get, api) => ({
      ...createLlmConsoleSlice(set, get, api),
    }),
    { name: "LlmConsoleStore" }
  )
);

// Re-export type
export type { LlmConsoleState };
