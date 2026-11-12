import { useMemo } from "react";
import type { ConvertOptions } from "@/lib/api";
import { useSettingsStore } from "@/stores/settings";

/** The conversion options from Settings, in the shape the API calls take. */
export function useConvertOptions(): ConvertOptions {
  const catalogName = useSettingsStore((s) => s.catalogName);
  const schemaName = useSettingsStore((s) => s.schemaName);
  const includeComments = useSettingsStore((s) => s.includeComments);
  const includeExpressionAudit = useSettingsStore((s) => s.includeExpressionAudit);
  const includePerformanceHints = useSettingsStore((s) => s.includePerformanceHints);
  const generateDdl = useSettingsStore((s) => s.generateDdl);
  const generateDab = useSettingsStore((s) => s.generateDab);
  const expandMacros = useSettingsStore((s) => s.expandMacros);
  return useMemo(
    () => ({
      catalogName,
      schemaName,
      includeComments,
      includeExpressionAudit,
      includePerformanceHints,
      generateDdl,
      generateDab,
      expandMacros,
    }),
    [
      catalogName,
      schemaName,
      includeComments,
      includeExpressionAudit,
      includePerformanceHints,
      generateDdl,
      generateDab,
      expandMacros,
    ],
  );
}
