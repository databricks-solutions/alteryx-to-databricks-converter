import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type AssessDefaults, type AssessResult } from "@/lib/api";

export function useAssess() {
  return useMutation<
    AssessResult,
    Error,
    { files: File[]; hours?: boolean; config?: Record<string, unknown> }
  >({
    mutationFn: ({ files, hours, config }) => api.assess(files, { hours, config }),
  });
}

export function useAssessDefaults() {
  return useQuery<AssessDefaults>({
    queryKey: ["assess-defaults"],
    queryFn: () => api.assessDefaults(),
    staleTime: Infinity,
  });
}
