import type { WorkflowAnalysis } from "./api";

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
