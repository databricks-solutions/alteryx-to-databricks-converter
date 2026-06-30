import { useMutation } from "@tanstack/react-query";
import { api, type ConversionResult } from "@/lib/api";

interface ConvertParams {
  file: File;
  catalogName?: string;
  schemaName?: string;
  includeComments?: boolean;
  includeExpressionAudit?: boolean;
  includePerformanceHints?: boolean;
  generateDdl?: boolean;
  generateDab?: boolean;
  expandMacros?: boolean;
}

export function useConversion() {
  return useMutation<ConversionResult, Error, ConvertParams>({
    mutationFn: ({
      file,
      catalogName,
      schemaName,
      includeComments,
      includeExpressionAudit,
      includePerformanceHints,
      generateDdl,
      generateDab,
      expandMacros,
    }) =>
      api.convert(file, {
        catalogName,
        schemaName,
        includeComments,
        includeExpressionAudit,
        includePerformanceHints,
        generateDdl,
        generateDab,
        expandMacros,
      }),
  });
}
