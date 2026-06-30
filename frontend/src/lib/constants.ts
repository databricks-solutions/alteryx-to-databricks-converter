import type { FormatId } from "@/lib/api";

/** Canonical display order for output formats (used by tabs and badges). */
export const FORMAT_ORDER: ReadonlyArray<FormatId> = [
  "pyspark",
  "dlt",
  "sql",
  "lakeflow",
];

/** Human-readable labels for output format IDs. */
export const FORMAT_LABELS: Record<string, string> = {
  pyspark: "PySpark",
  dlt: "Spark Declarative Pipelines",
  sql: "Spark SQL",
  lakeflow: "Lakeflow Designer",
};

/** Get the display label for a format, falling back to the raw ID. */
export function formatLabel(format: string): string {
  return FORMAT_LABELS[format] ?? format;
}
