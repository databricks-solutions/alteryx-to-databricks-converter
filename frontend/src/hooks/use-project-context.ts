import { useCallback, useMemo } from "react";
import { useParams } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  isMacroFile,
  type EstateSource,
  type Project,
  type WorkflowAnalysisSummary,
  type WorkflowConversionSummary,
  type WorkflowSource,
  type WorkflowStage,
} from "@/lib/api";
import { isLocalProjectId, useLocalProjectStore } from "@/stores/local-project";

/** One workflow as every step sees it, whichever kind of project it's in. */
export interface ProjectWorkflowView {
  id: string;
  file_name: string;
  stage: WorkflowStage;
  size_bytes: number;
  analysis: WorkflowAnalysisSummary | null;
  conversion: WorkflowConversionSummary | null;
}

export interface ProjectContext {
  /** The id in the URL, or null outside a project. */
  projectId: string | null;
  /** True for a database-backed project; false for a session-only one. */
  saved: boolean;
  /** A session-only project URL whose project no longer exists in this tab. */
  sessionGone: boolean;
  name: string;
  workflows: ProjectWorkflowView[];
  /** Changes only when the set of files (or their content) changes, so cached
   * results can tell whether they still describe the estate. */
  signature: string;
  /** True only on the first load of a saved project (not on background refetches). */
  isLoading: boolean;
  /** Set when a saved project can't be loaded. `hasData` tells a failed
   * background refresh (keep showing the project) from a failed first load. */
  error: Error | null;
  hasData: boolean;
  /** For multi-file calls (analyze, assess, portfolio, savings, batch). */
  source: EstateSource | null;
  /** For single-workflow calls (convert, review, advise, AI): the saved
   * project's reference, or the session file plus the session's macros. */
  workflowSource: (workflowId: string) => WorkflowSource | null;
  /** The workflow's file (a saved one is downloaded from the project). */
  getFile: (workflowId: string) => Promise<File>;
  /** A session project's macros (.yxmc), for a batch run on part of it. */
  localMacros: File[];
  /** Move one workflow forward to `stage` (never backward). */
  setStage: (workflowId: string, stage: WorkflowStage, conversion?: WorkflowConversionSummary) => Promise<void>;
  /** After a whole-estate pass: refetch a saved project, or record it locally. */
  afterEstatePass: (opts: { analyzed?: string[]; analysis?: Record<string, WorkflowAnalysisSummary> }) => void;
  /** After a batch conversion of a session-only project (a saved one is updated by the server). */
  afterBatch: (converted: { fileName: string; summary: WorkflowConversionSummary }[]) => void;
  refresh: () => void;
}

export function projectQueryKey(id: string | null) {
  return ["project", id] as const;
}

/**
 * The project the current screen works on, read from the URL. Every step uses
 * this, so they all read the same estate: saved projects come from the server
 * (no re-upload anywhere), session-only ones from the browser.
 */
export function useProjectContext(): ProjectContext {
  const params = useParams({ strict: false }) as { projectId?: string };
  const projectId = params.projectId ?? null;
  const isLocal = isLocalProjectId(projectId);
  const saved = projectId != null && !isLocal;
  const qc = useQueryClient();

  const query = useQuery<Project>({
    queryKey: projectQueryKey(projectId),
    queryFn: () => api.getProject(projectId!),
    enabled: saved,
    retry: false,
  });

  const localId = useLocalProjectStore((s) => s.id);
  const localName = useLocalProjectStore((s) => s.name);
  const localWorkflows = useLocalProjectStore((s) => s.workflows);
  const local = useLocalProjectStore.getState;
  // The URL's session project is the one in this tab only if the ids match.
  const localLive = isLocal && localId != null && localId === projectId;

  const workflows = useMemo<ProjectWorkflowView[]>(() => {
    if (isLocal) {
      return localLive
        ? localWorkflows.map((w) => ({
            id: w.id,
            file_name: w.file_name,
            stage: w.stage,
            size_bytes: w.file.size,
            analysis: w.analysis,
            conversion: w.conversion,
          }))
        : [];
    }
    return (query.data?.workflows ?? []).map((w) => ({
      id: w.id,
      file_name: w.file_name,
      stage: w.stage,
      size_bytes: w.size_bytes ?? 0,
      analysis: w.analysis ?? null,
      conversion: w.conversion ?? null,
    }));
  }, [isLocal, localLive, localWorkflows, query.data]);

  const signature = useMemo(() => {
    if (isLocal) {
      return localWorkflows
        .map((w) => `${w.file_name}:${w.file.size}:${w.file.lastModified}`)
        .sort()
        .join("|");
    }
    return (query.data?.workflows ?? [])
      .map((w) => `${w.file_name}:${w.content_hash ?? w.size_bytes ?? ""}`)
      .sort()
      .join("|");
  }, [isLocal, localWorkflows, query.data]);

  const refresh = useCallback(() => {
    if (saved) {
      qc.invalidateQueries({ queryKey: projectQueryKey(projectId) });
      qc.invalidateQueries({ queryKey: ["projects"] });
    }
  }, [qc, saved, projectId]);

  const source = useMemo<EstateSource | null>(() => {
    if (saved && projectId) return { projectId };
    if (localLive && localWorkflows.length > 0) return { files: localWorkflows.map((w) => w.file) };
    return null;
  }, [saved, localLive, projectId, localWorkflows]);

  const localMacros = useMemo(
    () => (localLive ? localWorkflows.filter((w) => isMacroFile(w.file_name)).map((w) => w.file) : []),
    [localLive, localWorkflows],
  );

  const workflowSource = useCallback(
    (workflowId: string): WorkflowSource | null => {
      if (saved && projectId) return { projectId, workflowId };
      const w = localLive ? localWorkflows.find((x) => x.id === workflowId) : undefined;
      return w ? { file: w.file, macros: localMacros } : null;
    },
    [saved, projectId, localLive, localWorkflows, localMacros],
  );

  const getFile = useCallback(
    async (workflowId: string): Promise<File> => {
      if (isLocal) {
        const w = local().workflows.find((x) => x.id === workflowId);
        if (!w) throw new Error("That workflow is no longer in this project.");
        return w.file;
      }
      const w = query.data?.workflows.find((x) => x.id === workflowId);
      if (!w || !projectId) throw new Error("That workflow is no longer in this project.");
      return api.getProjectWorkflowFile(projectId, workflowId, w.file_name);
    },
    [isLocal, local, query.data, projectId],
  );

  const setStage = useCallback(
    async (workflowId: string, stage: WorkflowStage, conversion?: WorkflowConversionSummary) => {
      if (isLocal) {
        const w = local().workflows.find((x) => x.id === workflowId);
        if (!w) return;
        if (conversion) local().setConversion(w.file_name, conversion);
        local().advance((x) => x.id === workflowId, stage);
        return;
      }
      if (!projectId) return;
      await api.updateWorkflowStage(
        projectId,
        workflowId,
        stage,
        conversion ? { key: "conversion_refs", value: { ...conversion } } : undefined,
      );
      refresh();
    },
    [isLocal, local, projectId, refresh],
  );

  const afterEstatePass = useCallback(
    (opts: { analyzed?: string[]; analysis?: Record<string, WorkflowAnalysisSummary> }) => {
      if (isLocal) {
        // Only for the session project this run belonged to.
        if (local().id !== projectId) return;
        if (opts.analysis) local().setAnalysis(opts.analysis);
        if (opts.analyzed) {
          const names = new Set(opts.analyzed);
          local().advance((w) => names.has(w.file_name), "assessed");
        }
        return;
      }
      refresh();
    },
    [isLocal, local, projectId, refresh],
  );

  const afterBatch = useCallback(
    (converted: { fileName: string; summary: WorkflowConversionSummary }[]) => {
      if (isLocal) {
        if (local().id !== projectId) return;
        for (const c of converted) local().setConversion(c.fileName, c.summary);
        return;
      }
      refresh();
    },
    [isLocal, local, projectId, refresh],
  );

  const name = isLocal ? (localLive ? (localName ?? "Session project") : "") : (query.data?.name ?? "");
  const error = saved ? (query.error as Error | null) : null;
  const hasData = isLocal ? localLive : query.data != null;
  const isLoading = saved && query.isLoading;

  return useMemo(
    () => ({
      projectId,
      saved,
      sessionGone: isLocal && !localLive,
      name,
      workflows,
      signature,
      isLoading,
      error,
      hasData,
      source,
      workflowSource,
      getFile,
      localMacros,
      setStage,
      afterEstatePass,
      afterBatch,
      refresh,
    }),
    [
      projectId,
      saved,
      isLocal,
      localLive,
      name,
      workflows,
      signature,
      isLoading,
      error,
      hasData,
      source,
      workflowSource,
      getFile,
      localMacros,
      setStage,
      afterEstatePass,
      afterBatch,
      refresh,
    ],
  );
}
