import { useMutation } from "@tanstack/react-query";
import { api, type ConvertOptions, type EstateSource } from "@/lib/api";
import { useBatchStore } from "@/stores/batch";

interface BatchParams extends ConvertOptions {
  source: EstateSource;
  /** For a saved project: convert only these file names. */
  workflowNames?: string[];
  /** The project this job belongs to. */
  projectId?: string | null;
}

export function useBatchConversion() {
  const startJob = useBatchStore((s) => s.startJob);
  const connectWs = useBatchStore((s) => s.connectWs);

  return useMutation<void, Error, BatchParams>({
    mutationFn: async ({ source, projectId, ...opts }) => {
      const { job_id, total_files } = await api.convertBatch(source, opts);
      startJob(job_id, total_files, projectId);
      connectWs(job_id);
    },
  });
}
