import { create } from "zustand";
import { persist } from "zustand/middleware";
import type {
  AnalysisResult,
  AssessResult,
  PortfolioReport,
  ReadinessResult,
  SavingsReport,
} from "@/lib/api";

/**
 * The "current estate" — one set of uploaded Alteryx files shared across every
 * analysis surface (Assess report, difficulty tiers, portfolio, savings,
 * readiness). Uploading on any surface populates this, so a user analyzes the
 * same estate five different ways without re-uploading it each time.
 *
 * Two tiers of state with different lifetimes:
 *   - `files` lives IN MEMORY only. A `File` can't be serialized to
 *     localStorage, so it survives navigation within a session but not a full
 *     reload. That still kills the "re-drop the same files on every tab" churn.
 *   - `results` are the derived, JSON-serializable API responses. They ARE
 *     persisted, so navigating away (or reloading) shows prior work instead of a
 *     blank upload form. Each result is stamped with the file signature that
 *     produced it so a stale result can be labeled.
 */

export function filesSignature(files: File[]): string {
  return files
    .map((f) => `${f.name}:${f.size}`)
    .sort()
    .join("|");
}

/** The payload type stored under each result kind. */
export interface EstateResultData {
  analyze: AnalysisResult;
  profile: AssessResult;
  portfolio: PortfolioReport;
  savings: SavingsReport;
  readiness: ReadinessResult;
}

export type EstateResultKind = keyof EstateResultData;

export interface StoredResult<T> {
  data: T;
  at: string; // ISO timestamp
  signature: string; // files signature that produced it
}

type ResultMap = {
  [K in EstateResultKind]?: StoredResult<EstateResultData[K]>;
};

interface EstateState {
  files: File[];
  results: ResultMap;
  setFiles: (files: File[]) => void;
  clearFiles: () => void;
  saveResult: <K extends EstateResultKind>(kind: K, data: EstateResultData[K]) => void;
  clearResult: (kind: EstateResultKind) => void;
  clearAll: () => void;
}

export const useEstateStore = create<EstateState>()(
  persist(
    (set, get) => ({
      files: [],
      results: {},

      setFiles: (files) => set({ files }),
      clearFiles: () => set({ files: [] }),

      saveResult: (kind, data) =>
        set((s) => ({
          results: {
            ...s.results,
            [kind]: {
              data,
              at: new Date().toISOString(),
              signature: filesSignature(get().files),
            },
          },
        })),

      clearResult: (kind) =>
        set((s) => {
          const results = { ...s.results };
          delete results[kind];
          return { results };
        }),

      clearAll: () => set({ files: [], results: {} }),
    }),
    {
      name: "a2d-estate",
      // Only the derived results are persistable; File objects are not.
      partialize: (s) => ({ results: s.results }),
    },
  ),
);

/**
 * True when a stored result was computed from a different file set than the one
 * currently loaded — so a view can label it "from a previously loaded estate."
 * A result with no files currently loaded is not considered stale (nothing to
 * compare against), so persisted work still shows after a reload.
 */
export function isStale(stored: StoredResult<unknown> | undefined, files: File[]): boolean {
  if (!stored || files.length === 0) return false;
  return stored.signature !== filesSignature(files);
}
