import { create } from "zustand";
import type {
  WorkflowAnalysisSummary,
  WorkflowConversionSummary,
  WorkflowStage,
} from "@/lib/api";

/**
 * A session-only project, for servers with no database (local development).
 *
 * It behaves like a saved project — upload once, every step reads the same
 * files — but lives in this browser tab only: a `File` can't be persisted, so a
 * reload clears it. The deployed app has a database and never uses this.
 */

export const LOCAL_PROJECT_ID = "local";

const STAGE_ORDER: WorkflowStage[] = ["uploaded", "assessed", "converted", "reviewed", "deployed"];

export interface LocalWorkflow {
  id: string;
  file_name: string;
  stage: WorkflowStage;
  file: File;
  analysis: WorkflowAnalysisSummary | null;
  conversion: WorkflowConversionSummary | null;
}

interface LocalProjectState {
  name: string | null;
  workflows: LocalWorkflow[];
  create: (name: string, files: File[]) => void;
  add: (files: File[]) => void;
  remove: (id: string) => void;
  rename: (name: string) => void;
  clear: () => void;
  /** Move workflows forward to `stage` (never backward). `match` picks them by id or file name. */
  advance: (match: (w: LocalWorkflow) => boolean, stage: WorkflowStage) => void;
  setAnalysis: (byFileName: Record<string, WorkflowAnalysisSummary>) => void;
  setConversion: (fileName: string, summary: WorkflowConversionSummary) => void;
}

let counter = 0;
const newId = () => `local-${Date.now().toString(36)}-${(counter++).toString(36)}`;

function upsert(workflows: LocalWorkflow[], files: File[]): LocalWorkflow[] {
  // Same rule as the server: re-adding a file name replaces that workflow.
  const next = [...workflows];
  for (const file of files) {
    const fresh: LocalWorkflow = {
      id: newId(),
      file_name: file.name,
      stage: "uploaded",
      file,
      analysis: null,
      conversion: null,
    };
    const at = next.findIndex((w) => w.file_name === file.name);
    if (at >= 0) next[at] = { ...fresh, id: next[at].id };
    else next.push(fresh);
  }
  return next.sort((a, b) => a.file_name.localeCompare(b.file_name));
}

export function isAtOrPast(stage: WorkflowStage, target: WorkflowStage): boolean {
  return STAGE_ORDER.indexOf(stage) >= STAGE_ORDER.indexOf(target);
}

export const useLocalProjectStore = create<LocalProjectState>((set) => ({
  name: null,
  workflows: [],
  create: (name, files) => set({ name: name || "Untitled migration", workflows: upsert([], files) }),
  add: (files) => set((s) => ({ workflows: upsert(s.workflows, files) })),
  remove: (id) => set((s) => ({ workflows: s.workflows.filter((w) => w.id !== id) })),
  rename: (name) => set({ name }),
  clear: () => set({ name: null, workflows: [] }),
  advance: (match, stage) =>
    set((s) => ({
      workflows: s.workflows.map((w) =>
        match(w) && !isAtOrPast(w.stage, stage) ? { ...w, stage } : w,
      ),
    })),
  setAnalysis: (byFileName) =>
    set((s) => ({
      workflows: s.workflows.map((w) =>
        byFileName[w.file_name] ? { ...w, analysis: byFileName[w.file_name] } : w,
      ),
    })),
  setConversion: (fileName, summary) =>
    set((s) => ({
      workflows: s.workflows.map((w) =>
        w.file_name === fileName
          ? { ...w, conversion: summary, stage: isAtOrPast(w.stage, "converted") ? w.stage : "converted" }
          : w,
      ),
    })),
}));
