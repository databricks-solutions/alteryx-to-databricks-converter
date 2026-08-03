import { useMutation } from "@tanstack/react-query";
import { api, type FormatId, type ReviewSession } from "@/lib/api";

interface ReviewParams {
  file: File;
  outputFormat?: FormatId;
}

export function useReview() {
  return useMutation<ReviewSession, Error, ReviewParams>({
    mutationFn: ({ file, outputFormat }) => api.review(file, outputFormat),
  });
}
