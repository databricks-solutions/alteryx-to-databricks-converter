import { useMemo } from "react";
import type { ConvertOptions } from "@/lib/api";
import { useSettingsStore } from "@/stores/settings";
import { useProjectSettingsStore } from "@/stores/project-settings";

/**
 * The conversion options in the shape the API calls take: the project's own
 * table location if it has one, otherwise the default from Settings, plus the
 * output options from Settings.
 */
export function useConvertOptions(projectId?: string | null): ConvertOptions {
  const defaultCatalog = useSettingsStore((s) => s.catalogName);
  const defaultSchema = useSettingsStore((s) => s.schemaName);
  const own = useProjectSettingsStore((s) => (projectId ? s.byProject[projectId] : undefined));
  const includeComments = useSettingsStore((s) => s.includeComments);
  const includeExpressionAudit = useSettingsStore((s) => s.includeExpressionAudit);
  const includePerformanceHints = useSettingsStore((s) => s.includePerformanceHints);
  const generateDdl = useSettingsStore((s) => s.generateDdl);
  const generateDab = useSettingsStore((s) => s.generateDab);
  const catalogName = own?.catalogName ?? defaultCatalog;
  const schemaName = own?.schemaName ?? defaultSchema;
  return useMemo(
    () => ({
      catalogName,
      schemaName,
      includeComments,
      includeExpressionAudit,
      includePerformanceHints,
      generateDdl,
      generateDab,
    }),
    [
      catalogName,
      schemaName,
      includeComments,
      includeExpressionAudit,
      includePerformanceHints,
      generateDdl,
      generateDab,
    ],
  );
}
