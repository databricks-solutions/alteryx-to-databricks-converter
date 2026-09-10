import { useMutation } from "@tanstack/react-query";
import { api, type AssessResult } from "@/lib/api";

export function useAssess() {
  return useMutation<AssessResult, Error, { files: File[]; hours?: boolean }>({
    mutationFn: ({ files, hours }) => api.assess(files, hours ?? false),
  });
}
