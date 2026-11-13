import { useMutation } from "@tanstack/react-query";
import { api, type ConversionResult, type ConvertOptions, type WorkflowSource } from "@/lib/api";

export function useConversion() {
  return useMutation<ConversionResult, Error, { source: WorkflowSource } & ConvertOptions>({
    mutationFn: ({ source, ...opts }) => api.convert(source, opts),
  });
}
