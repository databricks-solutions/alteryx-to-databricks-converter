import { create } from "zustand";
import { persist } from "zustand/middleware";
import { safeStorage } from "@/stores/safe-storage";
import type {
  AnalysisResult,
  AssessResult,
  PortfolioReport,
  ReadinessResult,
  SavingsReport,
} from "@/lib/api";

/**
 * Cached analysis results, per project.
 *
 * The files themselves live in the project (on the server, or in the browser
 * for a session-only project); this only keeps what each view computed from
 * them, so switching tabs or steps doesn't recompute. Each result is stamped
 * with the project's file signature: when workflows are added, removed or
 * replaced the signature changes, the cached result no longer matches, and the
 * view recomputes by itself.
 */

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
  signature: string; // project file signature that produced it
  /** The inputs it was computed with (savings assumptions, tier overrides), so a
   * view shows the same inputs next to the result instead of fresh defaults. */
  args?: unknown;
}

// Keep cached results for this many projects (most recently used); older ones
// are dropped so localStorage can't fill up over months of use.
const MAX_PROJECTS = 12;

type ResultMap = {
  [K in EstateResultKind]?: StoredResult<EstateResultData[K]>;
};

interface EstateState {
  byProject: Record<string, ResultMap>;
  saveResult: <K extends EstateResultKind>(
    projectId: string,
    kind: K,
    data: EstateResultData[K],
    signature: string,
    args?: unknown,
  ) => void;
  clearResult: (projectId: string, kind: EstateResultKind) => void;
  forgetProject: (projectId: string) => void;
}

export const useEstateStore = create<EstateState>()(
  persist(
    (set) => ({
      byProject: {},

      saveResult: (projectId, kind, data, signature, args) =>
        set((s) => {
          const { [projectId]: current, ...others } = s.byProject;
          // Most recently used last; drop the oldest beyond the cap.
          const kept = Object.entries(others).slice(-(MAX_PROJECTS - 1));
          return {
            byProject: {
              ...Object.fromEntries(kept),
              [projectId]: { ...current, [kind]: { data, at: new Date().toISOString(), signature, args } },
            },
          };
        }),

      clearResult: (projectId, kind) =>
        set((s) => {
          const current = { ...s.byProject[projectId] };
          delete current[kind];
          return { byProject: { ...s.byProject, [projectId]: current } };
        }),

      forgetProject: (projectId) =>
        set((s) => {
          const next = { ...s.byProject };
          delete next[projectId];
          return { byProject: next };
        }),
    }),
    { name: "a2d-estate-v2", storage: safeStorage },
  ),
);
