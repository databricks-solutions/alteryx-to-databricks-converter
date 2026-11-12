import { useCallback, useMemo } from "react";
import { useParams } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type EstateSource,
  type Project,
  type WorkflowAnalysisSummary,
  type WorkflowConversionSummary,
  type WorkflowSource,
  type WorkflowStage,
} from "@/lib/api";
import { LOCAL_PROJECT_ID, useLocalProjectStore } from "@/stores/local-project";

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
  name: string;
  workflows: ProjectWorkflowView[];
  /** Changes only when the set of files (or their content) changes, so cached
   * results can tell whether they still describe the estate. */
  signature: string;
  isLoading: boolean;
  /** Set when a saved project can't be loaded (unknown id, server down). */
  error: Error | null;
  /** For multi-file calls (analyze, assess, portfolio, savings, batch). */
  source: EstateSource | null;
  /** For single-workflow calls that accept a project reference (AI). */
  workflowSource: (workflowId: string) => WorkflowSource | null;
  /** The workflow's file, for single-file calls (convert, review, advise). */
  getFile: (workflowId: string) => Promise<File>;
  /** Move one workflow forward to `stage` (never backward). */
  setStage: (
    workflowId: string,
    stage: WorkflowStage,
    conversion?: WorkflowConversionSummary,
  ) => Promise<void>;
  /** After a whole-estate pass: refetch a saved project, or record it locally. */
  afterEstatePass: (opts: { assessed?: boolean; analysis?: Record<string, WorkflowAnalysisSummary> }) => void;
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
  const isLocal = projectId === LOCAL_PROJECT_ID;
  const saved = projectId != null && !isLocal;
  const qc = useQueryClient();

  const query = useQuery<Project>({
    queryKey: projectQueryKey(projectId),
    queryFn: () => api.getProject(projectId!),
    enabled: saved,
    retry: false,
  });

  const local = useLocalProjectStore();

  const workflows = useMemo<ProjectWorkflowView[]>(() => {
    if (isLocal) {
      return local.workflows.map((w) => ({
        id: w.id,
        file_name: w.file_name,
        stage: w.stage,
        size_bytes: w.file.size,
        analysis: w.analysis,
        conversion: w.conversion,
      }));
    }
    return (query.data?.workflows ?? []).map((w) => ({
      id: w.id,
      file_name: w.file_name,
      stage: w.stage,
      size_bytes: w.size_bytes ?? 0,
      analysis: w.analysis ?? null,
      conversion: w.conversion ?? null,
    }));
  }, [isLocal, local.workflows, query.data]);

  const signature = useMemo(() => {
    if (isLocal) {
      return local.workflows
        .map((w) => `${w.file_name}:${w.file.size}:${w.file.lastModified}`)
        .sort()
        .join("|");
    }
    return (query.data?.workflows ?? [])
      .map((w) => `${w.file_name}:${w.content_hash ?? w.size_bytes ?? ""}`)
      .sort()
      .join("|");
  }, [isLocal, local.workflows, query.data]);

  const refresh = useCallback(() => {
    if (saved) {
      qc.invalidateQueries({ queryKey: projectQueryKey(projectId) });
      qc.invalidateQueries({ queryKey: ["projects"] });
    }
  }, [qc, saved, projectId]);

  const source = useMemo<EstateSource | null>(() => {
    if (saved && projectId) return { projectId };
    if (isLocal && local.workflows.length > 0) return { files: local.workflows.map((w) => w.file) };
    return null;
  }, [saved, isLocal, projectId, local.workflows]);

  const workflowSource = useCallback(
    (workflowId: string): WorkflowSource | null => {
      if (saved && projectId) return { projectId, workflowId };
      const w = local.workflows.find((x) => x.id === workflowId);
      return w ? { file: w.file } : null;
    },
    [saved, projectId, local.workflows],
  );

  const getFile = useCallback(
    async (workflowId: string): Promise<File> => {
      if (isLocal) {
        const w = local.workflows.find((x) => x.id === workflowId);
        if (!w) throw new Error("That workflow is no longer in this project.");
        return w.file;
      }
      const w = query.data?.workflows.find((x) => x.id === workflowId);
      if (!w || !projectId) throw new Error("That workflow is no longer in this project.");
      return api.getProjectWorkflowFile(projectId, workflowId, w.file_name);
    },
    [isLocal, local.workflows, query.data, projectId],
  );

  const setStage = useCallback(
    async (workflowId: string, stage: WorkflowStage, conversion?: WorkflowConversionSummary) => {
      if (isLocal) {
        const w = local.workflows.find((x) => x.id === workflowId);
        if (!w) return;
        if (conversion) local.setConversion(w.file_name, conversion);
        local.advance((x) => x.id === workflowId, stage);
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
    (opts: { assessed?: boolean; analysis?: Record<string, WorkflowAnalysisSummary> }) => {
      if (isLocal) {
        if (opts.analysis) local.setAnalysis(opts.analysis);
        if (opts.assessed) local.advance((w) => w.stage === "uploaded", "assessed");
        return;
      }
      refresh();
    },
    [isLocal, local, refresh],
  );

  const afterBatch = useCallback(
    (converted: { fileName: string; summary: WorkflowConversionSummary }[]) => {
      if (isLocal) {
        for (const c of converted) local.setConversion(c.fileName, c.summary);
        return;
      }
      refresh();
    },
    [isLocal, local, refresh],
  );

  return {
    projectId,
    saved,
    name: isLocal ? (local.name ?? "Session project") : (query.data?.name ?? ""),
    workflows,
    signature,
    isLoading: saved && query.isLoading,
    error: saved ? (query.error as Error | null) : null,
    source,
    workflowSource,
    getFile,
    setStage,
    afterEstatePass,
    afterBatch,
    refresh,
  };
}
