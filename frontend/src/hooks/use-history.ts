import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useHistory() {
  return useQuery({
    queryKey: ["history"],
    queryFn: () => api.history(),
  });
}

export function useHistoryDetail(id: string | null) {
  return useQuery({
    queryKey: ["history", id],
    queryFn: () => api.historyDetail(id!),
    enabled: !!id,
  });
}

export function useDeleteConversion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.historyDelete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["history"] });
    },
  });
}
