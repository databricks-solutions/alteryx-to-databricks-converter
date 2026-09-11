import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

// The history route merges server history with local (in-browser) history and
// then filters/sorts/paginates the combined set client-side, so it needs the
// full remote list — a server page would paginate the wrong (unmerged) set.
// Default fetch was 50, which silently hid every conversion past the 50th.
// Fetch up to this bound instead so nothing is hidden; `total` still reports the
// true count if it ever exceeds the bound.
const HISTORY_FETCH_LIMIT = 500;

export function useHistory() {
  return useQuery({
    queryKey: ["history", HISTORY_FETCH_LIMIT],
    queryFn: () => api.history(HISTORY_FETCH_LIMIT, 0),
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
