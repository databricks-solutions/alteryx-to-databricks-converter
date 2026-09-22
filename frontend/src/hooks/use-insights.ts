import { useMutation, useQuery } from "@tanstack/react-query";
import {
  api,
  type AdvisorReport,
  type CloudName,
  type CostAssumptions,
  type PortfolioReport,
  type SavingsReport,
} from "@/lib/api";

export function usePortfolio() {
  return useMutation<PortfolioReport, Error, { files: File[] }>({
    mutationFn: ({ files }) => api.portfolio(files),
  });
}

export function useAdvise() {
  return useMutation<AdvisorReport, Error, { file: File; cloud?: CloudName }>({
    mutationFn: ({ file, cloud }) => api.advise(file, cloud),
  });
}

export function useSavings() {
  return useMutation<SavingsReport, Error, { files: File[]; config?: Record<string, unknown> }>({
    mutationFn: ({ files, config }) => api.savings(files, config),
  });
}

export function useSavingsDefaults() {
  return useQuery<CostAssumptions>({
    queryKey: ["savings-defaults"],
    queryFn: () => api.savingsDefaults(),
    staleTime: Infinity,
  });
}
