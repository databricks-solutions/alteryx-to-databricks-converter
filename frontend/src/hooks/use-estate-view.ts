import { useCallback, useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import type { EstateSource } from "@/lib/api";
import { useProjectContext, type ProjectContext } from "@/hooks/use-project-context";
import {
  useEstateStore,
  type EstateResultData,
  type EstateResultKind,
  type StoredResult,
} from "@/stores/estate";

interface EstateViewOptions<K extends EstateResultKind, A> {
  kind: K;
  run: (source: EstateSource, args: A | undefined) => Promise<EstateResultData[K]>;
  /** Run by itself when the view opens and nothing current is cached. */
  auto?: boolean;
  /** Called after a successful run (e.g. to record stages on the project). */
  onResult?: (data: EstateResultData[K], ctx: ProjectContext) => void;
}

/**
 * One analysis view over the open project's workflows (readiness report,
 * difficulty tiers, waves, savings, readiness prefill).
 *
 * There is no upload: the view reads the project. With `auto`, it runs the
 * first time it's shown and again whenever the project's files change; the
 * result is cached per project so switching tabs doesn't recompute.
 */
export function useEstateView<K extends EstateResultKind, A = undefined>({
  kind,
  run,
  auto = false,
  onResult,
}: EstateViewOptions<K, A>) {
  const ctx = useProjectContext();
  const projectId = ctx.projectId;
  const stored = useEstateStore((s) =>
    projectId ? (s.byProject[projectId]?.[kind] as StoredResult<EstateResultData[K]> | undefined) : undefined,
  );
  const saveResult = useEstateStore((s) => s.saveResult);

  const mutation = useMutation<EstateResultData[K], Error, { args?: A; signature: string }>({
    mutationFn: ({ args }) => {
      if (!ctx.source) throw new Error("This project has no workflows yet.");
      return run(ctx.source, args);
    },
    onSuccess: (data, { signature }) => {
      if (projectId) saveResult(projectId, kind, data, signature);
      onResult?.(data, ctx);
    },
  });

  const current = stored && stored.signature === ctx.signature ? stored : undefined;
  const lastRunSignature = useRef<string | null>(null);

  const rerun = useCallback(
    (args?: A) => {
      lastRunSignature.current = ctx.signature;
      mutation.mutate({ args, signature: ctx.signature });
    },
    [ctx.signature, mutation],
  );

  useEffect(() => {
    if (!auto || ctx.isLoading || !ctx.source || ctx.workflows.length === 0) return;
    if (current || mutation.isPending) return;
    // Once per file signature: an error isn't retried in a loop, but adding or
    // replacing a workflow (a new signature) runs it again.
    if (lastRunSignature.current === ctx.signature) return;
    rerun(undefined);
  }, [auto, ctx.isLoading, ctx.source, ctx.workflows.length, ctx.signature, current, mutation.isPending, rerun]);

  return {
    ctx,
    data: current?.data ?? null,
    computedAt: current?.at ?? null,
    isPending: mutation.isPending,
    error: mutation.error,
    rerun,
  };
}
