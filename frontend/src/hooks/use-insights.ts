import { useMutation } from "@tanstack/react-query";
import { api, type AdvisorReport, type CloudName, type PortfolioReport } from "@/lib/api";

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
