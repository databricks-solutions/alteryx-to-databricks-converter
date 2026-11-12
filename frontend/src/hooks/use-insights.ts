import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type AdvisorReport, type CloudName, type CostAssumptions } from "@/lib/api";

export function useAdvise() {
  return useMutation<AdvisorReport, Error, { file: File; cloud?: CloudName }>({
    mutationFn: ({ file, cloud }) => api.advise(file, cloud),
  });
}

export function useSavingsDefaults() {
  return useQuery<CostAssumptions>({
    queryKey: ["savings-defaults"],
    queryFn: () => api.savingsDefaults(),
    staleTime: Infinity,
  });
}
