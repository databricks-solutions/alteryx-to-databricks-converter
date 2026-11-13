import { useProjectContext } from "@/hooks/use-project-context";
import { useEstateStore, type EstateResultData, type EstateResultKind } from "@/stores/estate";

/** A view's cached result for the open project, if it still matches its files. */
export function useCurrentResult<K extends EstateResultKind>(kind: K): EstateResultData[K] | null {
  const ctx = useProjectContext();
  const stored = useEstateStore((s) => (ctx.projectId ? s.byProject[ctx.projectId]?.[kind] : undefined));
  if (!stored || stored.signature !== ctx.signature) return null;
  return stored.data as EstateResultData[K];
}
