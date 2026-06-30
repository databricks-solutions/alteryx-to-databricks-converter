import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useTools() {
  return useQuery({
    queryKey: ["tools"],
    queryFn: api.tools,
    staleTime: Infinity,
  });
}

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: api.stats,
    staleTime: 60_000,
  });
}
