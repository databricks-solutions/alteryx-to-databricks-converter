import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useBatchStore } from "@/stores/batch";

interface BatchParams {
  files: File[];
  catalogName?: string;
  schemaName?: string;
  includeComments?: boolean;
  includeExpressionAudit?: boolean;
  includePerformanceHints?: boolean;
  generateDdl?: boolean;
  generateDab?: boolean;
  expandMacros?: boolean;
}

export function useBatchConversion() {
  const startJob = useBatchStore((s) => s.startJob);
  const connectWs = useBatchStore((s) => s.connectWs);

  return useMutation<void, Error, BatchParams>({
    mutationFn: async ({ files, catalogName, schemaName, includeComments, includeExpressionAudit, includePerformanceHints, generateDdl, generateDab, expandMacros }) => {
      const { job_id, total_files } = await api.convertBatch(files, {
        catalogName,
        schemaName,
        includeComments,
        includeExpressionAudit,
        includePerformanceHints,
        generateDdl,
        generateDab,
        expandMacros,
      });
      startJob(job_id, total_files);
      connectWs(job_id);
    },
  });
}
