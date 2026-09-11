import type { WorkflowAnalysis } from "./api";

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

export function downloadAnalysisCSV(workflows: WorkflowAnalysis[]) {
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

  const csv = [
    headers.join(","),
    ...rows.map((r) =>
      r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","),
    ),
  ].join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "migration-analysis.csv";
  a.click();
  URL.revokeObjectURL(url);
}
