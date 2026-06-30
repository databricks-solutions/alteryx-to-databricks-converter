import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AnalysisResult } from "@/lib/api";

interface AnalysisStore {
  lastResult: AnalysisResult | null;
  lastAnalyzedAt: string | null;
  save: (result: AnalysisResult) => void;
  clear: () => void;
}

export const useAnalysisStore = create<AnalysisStore>()(
  persist(
    (set) => ({
      lastResult: null,
      lastAnalyzedAt: null,
      save: (result) =>
        set({ lastResult: result, lastAnalyzedAt: new Date().toISOString() }),
      clear: () => set({ lastResult: null, lastAnalyzedAt: null }),
    }),
    { name: "a2d-analysis" },
  ),
);
