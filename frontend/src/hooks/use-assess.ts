import { useQuery } from "@tanstack/react-query";
import { api, type AssessDefaults } from "@/lib/api";

export function useAssessDefaults() {
  return useQuery<AssessDefaults>({
    queryKey: ["assess-defaults"],
    queryFn: () => api.assessDefaults(),
    staleTime: Infinity,
  });
}
