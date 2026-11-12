import type { AssessResult, WorkflowAnalysis } from "./api";
import { downloadText } from "./files";

/** RFC-4180 field quoting: wrap in quotes and double any embedded quotes so a
 *  value containing a comma, quote, or newline can't shift or corrupt columns. */
export function csvField(value: string | number): string {
  return `"${String(value).replace(/"/g, '""')}"`;
}

/** Build the analysis CSV as a string (pure — no DOM). Separated from the
 *  download so the escaping is unit-testable. */
export function analysisToCsv(workflows: WorkflowAnalysis[]): string {
  const headers = [
    "Workflow",
    "Nodes",
    "Connections",
    "Coverage %",
    "Complexity Score",
    "Complexity Level",
    "Priority",
    "Effort",
    "Tool Types",
    "Unsupported Types",
    "Warnings",
  ];
  const rows = workflows.map((w) => [
    w.workflow_name,
    w.node_count,
    w.connection_count,
    w.coverage_percentage.toFixed(1),
    w.complexity_score.toFixed(2),
    w.complexity_level,
    w.migration_priority,
    w.estimated_effort,
    w.tool_types.join("; "),
    w.unsupported_types.join("; "),
    w.warnings.join("; "),
  ]);
  return [
    headers.map(csvField).join(","),
    ...rows.map((r) => r.map(csvField).join(",")),
  ].join("\n");
}

export function downloadAnalysisCSV(workflows: WorkflowAnalysis[], filename = "migration-analysis.csv") {
  downloadText(filename, analysisToCsv(workflows), "text/csv;charset=utf-8");
}

/** The difficulty-tier profile as CSV, one row per workflow. */
export function profileToCsv(result: AssessResult): string {
  const header = [
    "workflow_name",
    "file_name",
    "node_count",
    "connection_count",
    "unique_tool_types",
    "coverage_percentage",
    "complexity_level",
    "complexity_score",
    "unsupported_count",
    "expression_count",
    "max_dag_depth",
    "has_macros",
    "migration_priority",
    "estimated_effort",
    "estimated_hours",
  ];
  const rows = result.workflows.map((w) =>
    [
      w.workflow_name,
      w.file_name,
      w.node_count,
      w.connection_count,
      w.unique_tool_types,
      w.coverage_percentage.toFixed(1),
      w.complexity_level,
      w.complexity_score.toFixed(1),
      w.unsupported_count,
      w.expression_count,
      w.max_dag_depth,
      w.has_macros ? "yes" : "no",
      w.migration_priority,
      w.estimated_effort,
      w.estimated_hours ?? "",
    ]
      .map(csvField)
      .join(","),
  );
  return [header.map(csvField).join(","), ...rows].join("\n");
}
