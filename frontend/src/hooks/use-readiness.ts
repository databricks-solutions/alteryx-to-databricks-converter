import { useMutation, useQuery } from "@tanstack/react-query";
import {
  api,
  type ReadinessPrefill,
  type ReadinessQuestions,
  type ReadinessResult,
} from "@/lib/api";

export function useReadinessQuestions() {
  return useQuery<ReadinessQuestions>({
    queryKey: ["readiness-questions"],
    queryFn: () => api.readinessQuestions(),
    staleTime: Infinity,
  });
}

export function useReadinessScore() {
  return useMutation<
    ReadinessResult,
    Error,
    { answers: Record<string, string>; config?: Record<string, unknown> }
  >({
    mutationFn: ({ answers, config }) => api.readinessScore(answers, config),
  });
}

export function useReadinessPrefill() {
  return useMutation<ReadinessPrefill, Error, { files: File[] }>({
    mutationFn: ({ files }) => api.readinessPrefill(files),
  });
}
