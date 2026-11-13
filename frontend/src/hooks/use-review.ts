import { useMutation } from "@tanstack/react-query";
import { api, type FormatId, type ReviewSession, type WorkflowSource } from "@/lib/api";

interface ReviewParams {
  source: WorkflowSource;
  outputFormat?: FormatId;
}

export function useReview() {
  return useMutation<ReviewSession, Error, ReviewParams>({
    mutationFn: ({ source, outputFormat }) => api.review(source, outputFormat),
  });
}
