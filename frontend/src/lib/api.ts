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

  /** Actually stop server-side conversion (not just stop listening). */
  batchCancel: (jobId: string) =>
    request<{ job_id: string; status: string }>(`/convert/batch/${jobId}/cancel`, {
      method: "POST",
    }),

  analyze: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<AnalysisResult>("/analyze", { method: "POST", body: fd });
  },

  assess: (files: File[], opts?: { hours?: boolean; config?: Record<string, unknown> }) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("hours", String(opts?.hours ?? false));
    if (opts?.config && Object.keys(opts.config).length > 0) {
      fd.append("config", JSON.stringify(opts.config));
    }
    return request<AssessResult>("/assess", { method: "POST", body: fd });
  },

  assessDefaults: () => request<AssessDefaults>("/assess/config-defaults"),

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

  review: (file: File, outputFormat: FormatId = "pyspark") => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("output_format", outputFormat);
    return request<ReviewSession>("/review", { method: "POST", body: fd });
  },

  // ── Migration assistant (opt-in; requires a configured FMAPI endpoint) ──

  chatStatus: () => request<{ enabled: boolean }>("/chat/status"),

  chatStart: (file: File, outputFormat: FormatId = "pyspark") => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("output_format", outputFormat);
    return request<ChatSession>("/chat", { method: "POST", body: fd });
  },

  chatSend: (sessionId: string, message: string) =>
    request<{ session_id: string; reply: string }>(`/chat/${sessionId}/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    }),

  /** Returns the report as Markdown text (server sends it as an attachment). */
  chatReport: async (sessionId: string, answers?: Record<string, string>) => {
    const res = await fetch(`${BASE}/chat/${sessionId}/report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(answers ?? {}),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(body.detail || res.statusText);
    }
    return res.text();
  },

  // ── Estate-level insights ────────────────────────────────────────────

  portfolio: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<PortfolioReport>("/portfolio", { method: "POST", body: fd });
  },

  advise: (file: File, cloud: CloudName = "aws") => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("cloud", cloud);
    return request<AdvisorReport>("/advise", { method: "POST", body: fd });
  },

  // ── Savings / ROI estimator ──────────────────────────────────────────

  savings: (files: File[], config?: Record<string, unknown>) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    if (config && Object.keys(config).length > 0) {
      fd.append("config", JSON.stringify(config));
    }
    return request<SavingsReport>("/savings", { method: "POST", body: fd });
  },

  savingsDefaults: () => request<CostAssumptions>("/savings/config-defaults"),

  // ── Readiness questionnaire ──────────────────────────────────────────

  readinessQuestions: () => request<ReadinessQuestions>("/readiness/questions"),

  readinessScore: (answers: Record<string, string>, config?: Record<string, unknown>) =>
    request<ReadinessResult>("/readiness/score", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers, config }),
    }),

  readinessPrefill: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<ReadinessPrefill>("/readiness/prefill", { method: "POST", body: fd });
  },
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

export type FormatId = "pyspark" | "dlt" | "sql" | "lakeflow" | "designer";

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
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
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

export interface AssessWorkflow {
  workflow_name: string;
  file_name: string;
  node_count: number;
  connection_count: number;
  unique_tool_types: number;
  coverage_percentage: number;
  complexity_level: string;
  complexity_score: number;
  unsupported_count: number;
  expression_count: number;
  max_dag_depth: number;
  has_macros: boolean;
  migration_priority: string;
  estimated_effort: string;
  estimated_hours: number | null;
}

export interface AssessResult {
  totals: {
    workflows: number;
    tools: number;
    connections: number;
    expressions: number;
    data_sources: number;
    workflows_with_macros: number;
    unique_tool_types: number;
  };
  size_distribution: {
    avg_tools_per_workflow: number;
    max_tools: number;
    max_tools_workflow: string;
    avg_dag_depth: number;
    max_dag_depth: number;
    max_dag_depth_workflow: string;
  };
  difficulty_distribution: Record<string, number>;
  tool_difficulty: {
    counts: Record<string, number>;
    types: Record<string, string[]>;
  };
  total_hours: number | null;
  workflows: AssessWorkflow[];
}

export interface AssessDefaults {
  tiers: string[];
  category_tiers: Record<string, string>;
  hour_anchors: Record<string, number>;
  tools: { name: string; category: string; default: string }[];
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

// ── Interactive review workspace ─────────────────────────────────────

/** How the auto-conversion of one node turned out. */
export type ReviewStatus = "auto_accepted" | "needs_review" | "cannot_convert";

/** A reviewer's decision on one node. */
export type ReviewDecision = "pending" | "accepted" | "edited" | "rejected";

export interface ReviewNode {
  node_id: number;
  tool_type: string;
  annotation: string | null;
  position_x: number;
  position_y: number;
  status: ReviewStatus;
  confidence: number;
  conversion_method: string;
  generated_code: string;
  warnings: string[];
  decision: ReviewDecision;
  edited_code: string | null;
}

export interface ReviewEdge {
  source_id: number;
  target_id: number;
  origin_anchor: string;
  destination_anchor: string;
}

export interface ReviewSummary {
  total: number;
  needs_review: number;
  resolved: number;
  complete: boolean;
}

export interface ReviewSession {
  workflow_name: string;
  output_format: FormatId;
  summary: ReviewSummary;
  nodes: ReviewNode[];
  edges: ReviewEdge[];
}

// ── Migration assistant (advisory only — never edits generated code) ─────

/** One gap the deterministic converter could not fully handle. */
export interface MigrationGap {
  kind: "unsupported_tool" | "todo" | "review_warning" | "graph";
  summary: string;
  node_id: number | null;
  tool_type: string | null;
  detail: string;
}

export interface MigrationDecision {
  node_id: number;
  tool_type: string;
  annotation: string | null;
  confidence: number;
  conversion_method: string;
  notes: string[];
}

export interface MigrationContext {
  workflow_name: string;
  output_format: FormatId;
  node_count: number;
  edge_count: number;
  coverage: number | null;
  deploy_status: "ready" | "needs_review" | "cannot_deploy";
  gaps: MigrationGap[];
  decisions: MigrationDecision[];
  summary: { total_gaps: number; blocking_gaps: number };
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatSession {
  session_id: string;
  context: MigrationContext;
  messages: ChatMessage[];
  clarifying_questions: string[];
}

// ── Estate-level insights ────────────────────────────────────────────────

export type CloudName = "aws" | "azure" | "gcp";

export interface PortfolioSummary {
  workflow_count: number;
  dependency_count: number;
  shared_macro_count: number;
  duplicate_subflow_count: number;
  isolated_workflow_count: number;
  estimated_effort_days: number;
  wave_count: number;
}

export interface PortfolioDependency {
  producer: string;
  consumer: string;
  artifact: string;
}

export interface SharedMacro {
  macro_path: string;
  usage_count: number;
  used_by: string[];
}

export interface DuplicateSubflow {
  fingerprint: string;
  description: string;
  occurrence_count: number;
  found_in: string[];
}

export interface WaveEntry {
  workflow_name: string;
  file_path: string;
  node_count: number;
  coverage_pct: number;
  complexity_score: number;
  migration_priority: string;
  estimated_effort: string;
  value: number;
  readiness: number;
  effort: number;
  score: number;
  depends_on: string[];
}

export interface MigrationWave {
  wave: number;
  estimated_effort_days: number;
  workflows: WaveEntry[];
}

export interface PortfolioReport {
  generated_at: string;
  tool_version: string;
  summary: PortfolioSummary;
  dependencies: PortfolioDependency[];
  shared_macros: SharedMacro[];
  duplicate_subflows: DuplicateSubflow[];
  isolated_workflows: string[];
  migration_plan: { waves: MigrationWave[] };
}

export interface ClusterRecommendation {
  tier: "single-node" | "small" | "medium" | "large";
  workers: number;
  node_type_id: string;
  relative_dbu_per_hour: number;
  photon_recommended: boolean;
  rationale: string[];
}

export interface AdvisorHint {
  node_id: number;
  hint_type: string;
  priority: string;
  suggestion: string;
  code_snippet: string;
  tool_type: string;
}

export interface AdvisorReport {
  workflow_name: string;
  cluster: ClusterRecommendation;
  hints: AdvisorHint[];
  node_count: number;
  max_depth: number;
  summary: Record<string, unknown>;
}

// ── Savings / ROI ──────────────────────────────────────────────────────

export interface CostAssumptions {
  currency: string;
  designer_seats: number;
  designer_cost_per_seat_year: number;
  server_licenses: number;
  server_cost_per_license_year: number;
  developer_hourly_rate: number;
  automation_factor: number | null;
  review_hours_per_workflow: number;
  dbu_price: number;
  dbu_per_workflow_run: number;
  runs_per_month: number;
  annual_maintenance_savings: number;
  analysis_horizon_years: number;
  hour_anchors: Record<string, number>;
}

export interface SavingsLine {
  key: string;
  label: string;
  amount: number;
  kind: "one_time" | "annual";
  direction: "saving" | "cost" | "investment";
}

export interface SavingsReport {
  currency: string;
  estate: {
    workflow_count: number;
    total_manual_hours: number;
    hours_by_level: Record<string, number>;
    workflows_by_level: Record<string, number>;
    mean_coverage_pct: number;
  };
  assumptions: CostAssumptions;
  lines: SavingsLine[];
  headline: {
    automation_factor_effective: number;
    dev_hours_avoided: number;
    dev_time_saved: number;
    migration_investment: number;
    alteryx_license_savings: number;
    maintenance_savings: number;
    databricks_run_cost: number;
    net_annual_savings: number;
    cumulative_net: number;
    payback_months: number | null;
    roi_pct: number | null;
  };
  disclaimer: string;
  skipped_files?: string[];
}

// ── Readiness questionnaire ────────────────────────────────────────────

export interface ReadinessOption {
  value: string;
  label: string;
  score: number;
  tip: string | null;
}

export interface ReadinessQuestion {
  id: string;
  dimension: string;
  prompt: string;
  weight: number;
  options: ReadinessOption[];
}

export interface ReadinessQuestions {
  dimensions: {
    id: string;
    label: string;
    questions: ReadinessQuestion[];
  }[];
  config_defaults: {
    dimension_weights: Record<string, number>;
    tiers: { name: string; min_score: number }[];
    tip_score_threshold: number;
  };
}

export interface ReadinessTip {
  question_id: string;
  dimension: string;
  dimension_label: string;
  prompt: string;
  answer: string;
  score: number;
  tip: string;
}

export interface ReadinessResult {
  overall_score: number;
  tier: string;
  dimension_scores: Record<string, number>;
  dimension_labels: Record<string, string>;
  tips: ReadinessTip[];
  answered: number;
  total_questions: number;
  unanswered: string[];
  disclaimer: string;
}

export interface ReadinessPrefill {
  answers: Record<string, string>;
  workflow_count: number;
  skipped_files: string[];
}
