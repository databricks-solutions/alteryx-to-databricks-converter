import { useMutation } from "@tanstack/react-query";
import { api, type AnalysisResult } from "@/lib/api";

export function useAnalysis() {
  return useMutation<AnalysisResult, Error, File[]>({
    mutationFn: (files) => api.analyze(files),
  });
}
