import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type AdvisorReport, type CloudName, type CostAssumptions, type WorkflowSource } from "@/lib/api";

export function useAdvise() {
  return useMutation<AdvisorReport, Error, { source: WorkflowSource; cloud?: CloudName }>({
    mutationFn: ({ source, cloud }) => api.advise(source, cloud),
  });
}

export function useSavingsDefaults() {
  return useQuery<CostAssumptions>({
    queryKey: ["savings-defaults"],
    queryFn: () => api.savingsDefaults(),
    staleTime: Infinity,
  });
}
