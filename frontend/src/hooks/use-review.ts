import { useMutation } from "@tanstack/react-query";
import { api, type ConvertOptions, type FormatId, type ReviewSession, type WorkflowSource } from "@/lib/api";

interface ReviewParams {
  source: WorkflowSource;
  outputFormat?: FormatId;
  opts?: ConvertOptions;
}

export function useReview() {
  return useMutation<ReviewSession, Error, ReviewParams>({
    mutationFn: ({ source, outputFormat, opts }) => api.review(source, outputFormat, opts),
  });
}
