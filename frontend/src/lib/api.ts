const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  stats: () =>
    request<{
      supported_tools: number;
      total_tools: number;
      expression_functions: number;
      output_formats: number;
      version: string;
    }>("/stats"),

  tools: () =>
    request<{
      categories: Record<string, ToolInfo[]>;
      total_tools: number;
      supported_tools: number;
    }>("/tools"),

  convert: (
    file: File,
    opts?: {
      catalogName?: string;
      schemaName?: string;
      includeComments?: boolean;
      includeExpressionAudit?: boolean;
      includePerformanceHints?: boolean;
      generateDdl?: boolean;
      generateDab?: boolean;
      expandMacros?: boolean;
    },
  ) => {
    const fd = new FormData();
    fd.append("file", file);
    if (opts?.catalogName) fd.append("catalog_name", opts.catalogName);
    if (opts?.schemaName) fd.append("schema_name", opts.schemaName);
    if (opts?.includeComments !== undefined)
      fd.append("include_comments", String(opts.includeComments));
    if (opts?.includeExpressionAudit !== undefined)
      fd.append("include_expression_audit", String(opts.includeExpressionAudit));
    if (opts?.includePerformanceHints !== undefined)
      fd.append("include_performance_hints", String(opts.includePerformanceHints));
    if (opts?.generateDdl !== undefined)
      fd.append("generate_ddl", String(opts.generateDdl));
    if (opts?.generateDab !== undefined)
      fd.append("generate_dab", String(opts.generateDab));
    if (opts?.expandMacros !== undefined)
      fd.append("expand_macros", String(opts.expandMacros));
    return request<ConversionResult>("/convert", { method: "POST", body: fd });
  },

  convertBatch: (
    files: File[],
    opts?: {
      catalogName?: string;
      schemaName?: string;
      includeComments?: boolean;
      includeExpressionAudit?: boolean;
      includePerformanceHints?: boolean;
      generateDdl?: boolean;
      generateDab?: boolean;
      expandMacros?: boolean;
    },
  ) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    if (opts?.catalogName) fd.append("catalog_name", opts.catalogName);
    if (opts?.schemaName) fd.append("schema_name", opts.schemaName);
    if (opts?.includeComments !== undefined)
      fd.append("include_comments", String(opts.includeComments));
    if (opts?.includeExpressionAudit !== undefined)
      fd.append("include_expression_audit", String(opts.includeExpressionAudit));
    if (opts?.includePerformanceHints !== undefined)
      fd.append("include_performance_hints", String(opts.includePerformanceHints));
    if (opts?.generateDdl !== undefined)
      fd.append("generate_ddl", String(opts.generateDdl));
    if (opts?.generateDab !== undefined)
      fd.append("generate_dab", String(opts.generateDab));
    if (opts?.expandMacros !== undefined)
      fd.append("expand_macros", String(opts.expandMacros));
    return request<{ job_id: string; total_files: number }>("/convert/batch", {
      method: "POST",
      body: fd,
    });
  },

  batchDownload: (jobId: string) =>
    fetch(`${BASE}/convert/batch/${jobId}/download`).then((res) => {
      if (!res.ok) throw new Error("Download failed");
      return res.blob();
    }),

  batchStatus: (jobId: string) =>
    request<BatchStatus>(`/convert/batch/${jobId}`),

  analyze: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<AnalysisResult>("/analyze", { method: "POST", body: fd });
  },

  history: (limit = 50, offset = 0) =>
    request<HistoryListResponse>(`/history?limit=${limit}&offset=${offset}`),

  historyDetail: (id: string) =>
    request<ConversionResult & { id: string }>(`/history/${id}`),

  historyDelete: (id: string) =>
    request<{ ok: boolean }>(`/history/${id}`, { method: "DELETE" }),

  validate: (code: string, filename?: string) =>
    request<ValidateResponse>("/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, filename: filename || "<input>" }),
    }),
};

// ── Types ────────────────────────────────────────────────────────────

export interface ToolInfo {
  tool_type: string;
  category: string;
  supported: boolean;
  conversion_method: string | null;
  description: string | null;
  databricks_equivalent: string | null;
}

export interface GeneratedFile {
  filename: string;
  content: string;
  file_type: string;
}

export interface DagNode {
  node_id: number;
  tool_type: string;
  annotation: string | null;
  position_x: number;
  position_y: number;
  conversion_confidence: number;
  conversion_method: string;
}

export interface DagEdge {
  source_id: number;
  target_id: number;
  origin_anchor: string;
  destination_anchor: string;
}

export interface DagData {
  nodes: DagNode[];
  edges: DagEdge[];
}

export interface ExpressionAuditEntry {
  node_id: number;
  tool_type: string;
  field_name: string;
  original_expression: string;
  translation_method: string;
  confidence: number;
  warnings: string[];
}

export interface PerformanceHint {
  node_id: number;
  hint_type: string;
  priority: string;
  suggestion: string;
  code_snippet: string;
  tool_type: string;
}

export interface NodeCodeMapping {
  node_id: number;
  tool_type: string;
  start_line: number;
  end_line: number;
  file_index: number;
}

export interface ConfidenceDimension {
  name: string;
  score: number;
  weight: number;
  details: string;
}

export interface ConfidenceScore {
  overall: number;
  level: string;
  dimensions: ConfidenceDimension[];
}

export type FormatId = "pyspark" | "dlt" | "sql" | "lakeflow";

export interface FormatResult {
  format: FormatId;
  status: "success" | "failed";
  files: GeneratedFile[];
  stats: { coverage_percentage?: number; [k: string]: unknown };
  warnings: string[];
  confidence: ConfidenceScore | null;
  error: string | null;
}

export interface ConversionResult {
  workflow_name: string;
  node_count: number;
  edge_count: number;
  warnings: string[];
  dag_data: DagData | null;
  expression_audit?: ExpressionAuditEntry[] | null;
  performance_hints?: PerformanceHint[] | null;
  node_code_mappings?: NodeCodeMapping[] | null;
  best_format: string;
  formats: Record<string, FormatResult>;
  /** Single source of truth for the headline coverage metric. Mirrors the
   *  best-format coverage; null if every format failed. */
  coverage?: number | null;
  context_id?: string | null;
}

export interface ConversionErrorDetail {
  message: string;
  type: string;
  node_id?: number;
  severity?: string;
}

export interface FileResult {
  file_name: string;
  workflow_name: string;
  success: boolean;
  node_count: number;
  edge_count: number;
  warnings: string[];
  formats: Record<string, FormatResult>;
  best_format: string;
}

export interface BatchMetrics {
  duration_seconds: number;
  total_files: number;
  successful_files: number;
  failed_files: number;
  partial_files: number;
  total_nodes: number;
  total_errors: number;
  total_warnings: number;
  avg_coverage_percentage: number;
}

export interface BatchStatus {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  total: number;
  file_results: FileResult[];
  batch_metrics: BatchMetrics | null;
  errors_by_kind: Record<string, number> | null;
}

export interface WorkflowAnalysis {
  file_name: string;
  workflow_name: string;
  node_count: number;
  connection_count: number;
  coverage_percentage: number;
  complexity_score: number;
  complexity_level: string;
  migration_priority: string;
  estimated_effort: string;
  tool_types: string[];
  unsupported_types: string[];
  warnings: string[];
}

export interface AnalysisResult {
  total_workflows: number;
  total_nodes: number;
  avg_coverage: number;
  avg_complexity: number;
  workflows: WorkflowAnalysis[];
  tool_frequency: Record<string, number>;
  unsupported_tools: string[];
}

export interface HistoryListItem {
  id: string;
  workflow_name: string;
  output_format: string;
  created_at: string;
  node_count: number;
  edge_count: number;
  coverage_percentage: number | null;
}

export interface HistoryListResponse {
  items: HistoryListItem[];
  total: number;
}

export interface FileValidationResult {
  filename: string;
  is_valid: boolean;
  errors: string[];
}

export interface ValidateResponse {
  results: FileValidationResult[];
  all_valid: boolean;
}
