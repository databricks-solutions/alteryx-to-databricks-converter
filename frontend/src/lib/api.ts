const BASE = "/api";

/**
 * Where a multi-file call gets its workflows: a saved project (the server reads
 * the stored files — nothing is re-uploaded) or, for a session-only project when
 * no database is configured, the files held in the browser. `macros` are .yxmc
 * files the workflows may call that aren't among `files` (a batch run on part
 * of a session project); a saved project's macros come from the server.
 */
/** GET /api/status. */
export interface ServerStatus {
  projects: { configured: boolean };
}

export type EstateSource = { projectId: string } | { files: File[]; macros?: File[] };

function appendSource(fd: FormData, source: EstateSource) {
  if ("projectId" in source) fd.append("project_id", source.projectId);
  else {
    source.files.forEach((f) => fd.append("files", f));
    source.macros?.forEach((f) => fd.append("macros", f));
  }
}

/** One workflow for a single-workflow call: a saved project's (its macros come
 * with it), or a browser file plus the session project's macros. */
export type WorkflowSource = { projectId: string; workflowId: string } | { file: File; macros?: File[] };

function appendWorkflow(fd: FormData, source: WorkflowSource) {
  if ("file" in source) {
    fd.append("file", source.file);
    source.macros?.forEach((f) => fd.append("macros", f));
  } else {
    fd.append("project_id", source.projectId);
    fd.append("workflow_id", source.workflowId);
  }
}

/** True for an Alteryx macro file (.yxmc). */
export function isMacroFile(name: string): boolean {
  return name.toLowerCase().endsWith(".yxmc");
}

export interface ConvertOptions {
  catalogName?: string;
  schemaName?: string;
  includeComments?: boolean;
  includeExpressionAudit?: boolean;
  includePerformanceHints?: boolean;
  generateDdl?: boolean;
  generateDab?: boolean;
}

function appendOptions(fd: FormData, opts?: ConvertOptions) {
  if (opts?.catalogName) fd.append("catalog_name", opts.catalogName);
  if (opts?.schemaName) fd.append("schema_name", opts.schemaName);
  if (opts?.includeComments !== undefined) fd.append("include_comments", String(opts.includeComments));
  if (opts?.includeExpressionAudit !== undefined)
    fd.append("include_expression_audit", String(opts.includeExpressionAudit));
  if (opts?.includePerformanceHints !== undefined)
    fd.append("include_performance_hints", String(opts.includePerformanceHints));
  if (opts?.generateDdl !== undefined) fd.append("generate_ddl", String(opts.generateDdl));
  if (opts?.generateDab !== undefined) fd.append("generate_dab", String(opts.generateDab));
}

async function requestText(path: string, init?: RequestInit): Promise<string> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) throw await failure(res);
  return res.text();
}

/** A failed API call, with the HTTP status so callers can tell cases apart
 * (e.g. 503 "no database configured" vs 503 "database not responding"). */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function failure(res: Response): Promise<ApiError> {
  const body = await res.json().catch(() => ({ detail: res.statusText }));
  const detail = typeof body.detail === "string" ? body.detail : body.error || res.statusText;
  return new ApiError(detail || `Request failed (${res.status})`, res.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) throw await failure(res);
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

  convert: (source: WorkflowSource, opts?: ConvertOptions) => {
    const fd = new FormData();
    appendWorkflow(fd, source);
    appendOptions(fd, opts);
    return request<ConversionResult>("/convert", { method: "POST", body: fd });
  },

  /** Convert many workflows. For a saved project, ``workflowNames`` narrows the
   * run to a selection (file names); omitted, the whole project converts. */
  convertBatch: (source: EstateSource, opts?: ConvertOptions & { workflowNames?: string[] }) => {
    const fd = new FormData();
    appendSource(fd, source);
    appendOptions(fd, opts);
    if ("projectId" in source && opts?.workflowNames) {
      fd.append("workflow_names", JSON.stringify(opts.workflowNames));
    }
    return request<{ job_id: string; total_files: number }>("/convert/batch", {
      method: "POST",
      body: fd,
    });
  },

  batchDownload: async (jobId: string) => {
    const res = await fetch(`${BASE}/convert/batch/${jobId}/download`);
    if (!res.ok) throw await failure(res);
    return res.blob();
  },

  /** Actually stop server-side conversion (not just stop listening). */
  batchCancel: (jobId: string) =>
    request<{ job_id: string; status: string }>(`/convert/batch/${jobId}/cancel`, {
      method: "POST",
    }),

  analyze: (source: EstateSource) => {
    const fd = new FormData();
    appendSource(fd, source);
    return request<AnalysisResult>("/analyze", { method: "POST", body: fd });
  },

  assess: (source: EstateSource, opts?: { hours?: boolean; config?: Record<string, unknown> }) => {
    const fd = new FormData();
    appendSource(fd, source);
    fd.append("hours", String(opts?.hours ?? false));
    if (opts?.config && Object.keys(opts.config).length > 0) {
      fd.append("config", JSON.stringify(opts.config));
    }
    return request<AssessResult>("/assess", { method: "POST", body: fd });
  },

  assessDefaults: () => request<AssessDefaults>("/assess/config-defaults"),

  validate: (code: string, filename?: string) =>
    request<ValidateResponse>("/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, filename: filename || "<input>" }),
    }),

  review: (source: WorkflowSource, outputFormat: FormatId = "pyspark", opts?: ConvertOptions) => {
    const fd = new FormData();
    appendWorkflow(fd, source);
    appendOptions(fd, opts);
    fd.append("output_format", outputFormat);
    return request<ReviewSession>("/review", { method: "POST", body: fd });
  },

  // ── Estate-level insights ────────────────────────────────────────────

  portfolio: (source: EstateSource) => {
    const fd = new FormData();
    appendSource(fd, source);
    return request<PortfolioReport>("/portfolio", { method: "POST", body: fd });
  },

  advise: (source: WorkflowSource, cloud: CloudName = "aws") => {
    const fd = new FormData();
    appendWorkflow(fd, source);
    fd.append("cloud", cloud);
    return request<AdvisorReport>("/advise", { method: "POST", body: fd });
  },

  // ── Savings / ROI estimator ──────────────────────────────────────────

  savings: (source: EstateSource, config?: Record<string, unknown>) => {
    const fd = new FormData();
    appendSource(fd, source);
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

  readinessPrefill: (source: EstateSource) => {
    const fd = new FormData();
    appendSource(fd, source);
    return request<ReadinessPrefill>("/readiness/prefill", { method: "POST", body: fd });
  },

  // ── Migration Project ────────────────────────────────────────────────

  /** What the server has turned on (no failing request needed to find out). */
  status: () => request<ServerStatus>("/status"),

  listProjects: () => request<{ projects: ProjectSummary[]; total: number }>("/projects"),

  getProject: (id: string) => request<Project>(`/projects/${id}`),

  createProject: (name: string, files: File[]) => {
    const fd = new FormData();
    fd.append("name", name);
    files.forEach((f) => fd.append("files", f));
    return request<Project>("/projects", { method: "POST", body: fd });
  },

  addProjectWorkflows: (id: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<Project>(`/projects/${id}/workflows`, { method: "POST", body: fd });
  },

  deleteProject: (id: string) => request<{ deleted: string }>(`/projects/${id}`, { method: "DELETE" }),

  renameProject: (id: string, name: string) =>
    request<Project>(`/projects/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),

  removeProjectWorkflow: (projectId: string, workflowId: string) =>
    request<Project>(`/projects/${projectId}/workflows/${workflowId}`, { method: "DELETE" }),

  /** Move a workflow forward to ``stage`` (the server never moves it backward),
   * optionally storing the artifact that stage produced. */
  updateWorkflowStage: (
    projectId: string,
    workflowId: string,
    stage: WorkflowStage,
    artifact?: { key: "conversion_refs" | "review_decisions"; value: Record<string, unknown> },
  ) =>
    request<Project>(`/projects/${projectId}/workflows/${workflowId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        artifact ? { stage, artifact_key: artifact.key, artifact: artifact.value } : { stage },
      ),
    }),

  /** Fetch a stored workflow's bytes as a File, so a screen runs it without a re-upload. */
  getProjectWorkflowFile: async (projectId: string, workflowId: string, fileName: string) => {
    const res = await fetch(`${BASE}/projects/${projectId}/workflows/${workflowId}/file`);
    if (!res.ok) throw await failure(res);
    const blob = await res.blob();
    return new File([blob], fileName, { type: "application/octet-stream" });
  },

  // ── AI completion (opt-in; the only calls that return model-written code) ──

  aiStatus: () => request<{ enabled: boolean }>("/ai/status"),

  aiGaps: (source: WorkflowSource, opts?: ConvertOptions) => {
    const fd = new FormData();
    appendWorkflow(fd, source);
    appendOptions(fd, opts);
    return request<MigrationContext>("/ai/gaps", { method: "POST", body: fd });
  },

  /** AI code for one step, for Review (PySpark). `hint` is the reviewer's note. */
  aiSuggest: (source: WorkflowSource, nodeId: number, opts?: ConvertOptions, hint?: string) => {
    const fd = new FormData();
    appendWorkflow(fd, source);
    appendOptions(fd, opts);
    fd.append("node_id", String(nodeId));
    if (hint && hint.trim()) fd.append("hint", hint.trim());
    return request<AISuggestion>("/ai/suggest", { method: "POST", body: fd });
  },

  aiComplete: (source: WorkflowSource, opts?: ConvertOptions) => {
    const fd = new FormData();
    appendWorkflow(fd, source);
    appendOptions(fd, opts);
    return request<AICompletion>("/ai/complete", { method: "POST", body: fd });
  },

  /** The Markdown suggestions notes, as text (the server sends an attachment). */
  aiNotes: (source: WorkflowSource, opts?: ConvertOptions) => {
    const fd = new FormData();
    appendWorkflow(fd, source);
    appendOptions(fd, opts);
    return requestText("/ai/notes", { method: "POST", body: fd });
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
  /** The uploaded name (differs from file_name for a .yxzp package). */
  source_file_name?: string;
  coverage?: number;
  errors?: { message: string; severity?: string }[];
  workflow_name: string;
  success: boolean;
  node_count: number;
  edge_count: number;
  warnings: string[];
  /** Left out of live progress messages (too heavy to stream). */
  formats?: Record<string, FormatResult>;
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
  source_file_name?: string | null;
  workflow_name: string;
  node_count: number;
  connection_count: number;
  /** Supported tools over all tools (canvas comments excluded): the same figure
   * Convert shows after converting. */
  coverage_percentage: number;
  /** Share of distinct tool types that are supported (a different question). */
  type_coverage_percentage?: number;
  tool_count?: number;
  supported_tool_count?: number;
  complexity_score: number;
  complexity_level: string;
  migration_priority: string;
  estimated_effort: string;
  tool_types: string[];
  unsupported_types: string[];
  unresolved_macros?: UnresolvedMacro[];
  warnings: string[];
}

/** A macro call that wasn't expanded (file missing, batch or iterative, ...). */
export interface UnresolvedMacro {
  name: string;
  reason: string;
}

export interface AnalysisResult {
  /** Uploaded names that couldn't be read or analyzed. */
  skipped_files?: string[];
  total_workflows: number;
  total_nodes: number;
  avg_coverage: number;
  avg_complexity: number;
  workflows: WorkflowAnalysis[];
  tool_frequency: Record<string, number>;
  unsupported_tools: string[];
  /** Macro calls that weren't expanded, by macro file name. */
  unresolved_macros?: UnresolvedMacro[];
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
  skipped_files?: string[];
  /** Uploaded names that were profiled. */
  analyzed_files?: string[];
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
  /** Mapping confidence 0..1; 0 when the step isn't converted or isn't finished. */
  confidence: number;
  /** The generated code still has a converter TODO / PLACEHOLDER / CANNOT CONVERT line. */
  unfinished: boolean;
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

// ── Migration gaps (what the deterministic converter couldn't finish) ─────

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

/** A step AI completion would work on (from /api/ai/gaps). */
export interface CompletableStep {
  node_id: number;
  tool_type: string | null;
  reason: string;
}

export interface MigrationContext {
  /** Present on /api/ai/gaps: the steps AI completion would fill in. */
  completable?: CompletableStep[];
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

// ── Migration Project ──────────────────────────────────────────────────

export type WorkflowStage = "uploaded" | "assessed" | "converted" | "reviewed" | "deployed";

/** Per-workflow analysis summary kept on a saved project. */
export interface WorkflowAnalysisSummary {
  coverage_percentage?: number;
  tool_count?: number;
  supported_tool_count?: number;
  complexity_score?: number;
  complexity_level?: string;
  migration_priority?: string;
  estimated_effort?: string;
}

/** Last conversion kept on a project workflow. */
export interface WorkflowConversionSummary {
  coverage?: number | null;
  best_format?: string;
  warnings?: number;
  at?: string;
}

/** One step's AI suggestion for Review. `code` is the step as Review shows it
 * (from its "# Step N:" line), with the AI code between the markers. */
export interface AISuggestion {
  node_id: number;
  status: "completed" | "failed" | "skipped";
  reason: string;
  code: string | null;
  before: string;
}

/** A reviewer's saved decisions for one workflow, per step. `base` is a hash of
 * the generated code the decision was made on, so a decision is only restored
 * while that step's code is unchanged. */
export interface ReviewDecisionsRecord {
  output_format: FormatId;
  nodes: Record<
    string,
    { decision: ReviewDecision; code: string | null; source: "ai" | "user" | null; base: string }
  >;
  saved_at: string;
}

export interface ProjectWorkflow {
  id: string;
  file_name: string;
  stage: WorkflowStage;
  analysis: WorkflowAnalysisSummary | null;
  conversion?: WorkflowConversionSummary | null;
  review?: ReviewDecisionsRecord | null;
  size_bytes?: number;
  content_hash?: string;
  updated_at: string;
}

export interface ProjectRollups {
  total_workflows?: number;
  stage_counts?: Record<WorkflowStage, number>;
  mean_coverage_pct?: number;
}

export interface ProjectSummary {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  rollups: ProjectRollups;
}

export interface Project extends ProjectSummary {
  workflows: ProjectWorkflow[];
  /** On create/add: what happened to each file sent. */
  changes?: { added: string[]; replaced: string[]; unchanged: string[] };
}

// ── AI completion ──────────────────────────────────────────────────────

export interface CellCompletion {
  node_id: number | null;
  tool_type: string | null;
  status: "completed" | "failed" | "skipped";
  reason: string;
  before: string;
  after: string;
}

export interface AICompletion {
  workflow_name: string;
  filename: string;
  deterministic_filename: string;
  content: string;
  cells: CellCompletion[];
  summary: { cells_needing_work: number; completed: number; failed: number; skipped: number };
}
