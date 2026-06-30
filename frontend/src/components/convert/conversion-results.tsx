import type {
  ConversionResult,
  ExpressionAuditEntry,
  FormatResult,
  GeneratedFile,
  PerformanceHint,
} from "@/lib/api";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { CodeBlock } from "@/components/shared/code-block";
import { MetricCard } from "@/components/shared/metric-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { motion, AnimatePresence } from "motion/react";
import {
  GitBranch,
  Network,
  FileCode,
  Percent,
  Download,
  Workflow,
  Zap,
  FileSearch,
  Shield,
  CheckCircle,
  Info,
  TriangleAlert,
  XCircle,
  Ban,
  AlertTriangle,
  HelpCircle,
} from "lucide-react";
import * as Collapsible from "@radix-ui/react-collapsible";
import { useEffect, useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";
import {
  downloadAllFormatsAsZip,
  downloadFormatAsZip,
} from "@/lib/download";
import { FORMAT_ORDER, formatLabel } from "@/lib/constants";
import {
  deriveDeployStatus,
  DEPLOY_THRESHOLDS,
  type DeployStatus,
} from "@/lib/deploy-status";
import {
  categorizeAcrossAllFormats,
  categorizeForFormat,
  categorizeWarnings,
  parseWarnings,
  type CategorizedWarnings,
  type ParsedWarning,
} from "@/lib/warning-parsing";
import { WorkflowGraph } from "./workflow-graph";

type ViewMode = "code" | "workflow";

interface ConversionResultsProps {
  result: ConversionResult;
}

function findFileLineForNode(
  files: GeneratedFile[],
  nodeId: number,
): { fileIndex: number; line: number } | null {
  const patterns = [
    new RegExp(`(^|\\s)#\\s*Step\\s+${nodeId}\\b`),
    new RegExp(`(^|\\s)--\\s*Step\\s+${nodeId}\\b`),
    new RegExp(`\\bstep_${nodeId}_`),
  ];
  for (let fi = 0; fi < files.length; fi++) {
    const lines = files[fi].content.split("\n");
    for (let i = 0; i < lines.length; i++) {
      if (patterns.some((p) => p.test(lines[i]))) {
        return { fileIndex: fi, line: i + 1 };
      }
    }
  }
  return null;
}

export function ConversionResults({ result }: ConversionResultsProps) {
  const [viewMode, setViewMode] = useState<ViewMode>("code");
  const initialFormat = useMemo(() => {
    if (result.best_format && result.formats[result.best_format]) {
      return result.best_format;
    }
    const firstSuccess = FORMAT_ORDER.find(
      (f) => result.formats[f]?.status === "success",
    );
    return firstSuccess ?? FORMAT_ORDER[0];
  }, [result]);
  const [activeFormat, setActiveFormat] = useState<string>(initialFormat);
  const activeFormatResult: FormatResult | undefined =
    result.formats[activeFormat];
  const activeFiles = activeFormatResult?.files ?? [];
  const [activeFile, setActiveFile] = useState<string | undefined>(
    activeFiles[0]?.filename,
  );
  const [highlightLine, setHighlightLine] = useState<number | undefined>();

  // Reset active file when active format changes
  useEffect(() => {
    setActiveFile(activeFiles[0]?.filename);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFormat]);

  const bestFormat = result.best_format;
  const bestFormatResult: FormatResult | null = bestFormat
    ? result.formats[bestFormat] ?? null
    : null;
  // Coverage % single source of truth: prefer the top-level `result.coverage`
  // (mirrors best-format coverage on the server) and fall back to the
  // best-format's stats dict. Earlier code tried to read a non-existent
  // top-level field and rendered "0%".
  const bestCoverage =
    typeof result.coverage === "number"
      ? result.coverage
      : typeof bestFormatResult?.stats?.coverage_percentage === "number"
        ? (bestFormatResult.stats.coverage_percentage as number)
        : null;
  const bestConfidence = bestFormatResult?.confidence ?? null;

  // Files = sum across formats deduped by filename
  const totalFiles = useMemo(() => {
    const seen = new Set<string>();
    for (const fr of Object.values(result.formats)) {
      if (fr.status !== "success") continue;
      for (const f of fr.files) seen.add(f.filename);
    }
    return seen.size;
  }, [result.formats]);

  const hasDag = !!(result.dag_data && result.dag_data.nodes.length > 0);
  const hasExprAudit =
    result.expression_audit && result.expression_audit.length > 0;
  const hasPerfHints =
    result.performance_hints && result.performance_hints.length > 0;

  // ── Warning categorization (workflow-level only — drives the workflow
  // warnings panel below the metrics) ──────────────────────────────────────
  const parsedWorkflowWarnings = useMemo(
    () => parseWarnings(result.warnings),
    [result.warnings],
  );
  const categorized = useMemo(
    () => categorizeWarnings(parsedWorkflowWarnings),
    [parsedWorkflowWarnings],
  );

  // ── Aggregated categorization (workflow + every per-format warning list)
  // drives the headline counts row so it doesn't contradict the per-format
  // tabs. Expression fallbacks + missing-generator + per-format unsupported
  // entries live in `formats[fmt].warnings`, NOT in workflow-level warnings,
  // so reading only `result.warnings` for the headline counts is wrong. ────
  const aggregated = useMemo(() => {
    const formatWarningLists = Object.values(result.formats).map(
      (f) => f.warnings ?? [],
    );
    return categorizeAcrossAllFormats(result.warnings, formatWarningLists);
  }, [result.warnings, result.formats]);

  // ── Counts row inputs ────────────────────────────────────────────────────
  const totalNodes = result.node_count;
  // Unique node ids with an unsupported tool (across all formats, deduped).
  const unsupportedNodeIds = useMemo(
    () =>
      new Set(
        aggregated.unsupported
          .map((w) => w.nodeId)
          .filter((id): id is number => id !== undefined),
      ),
    [aggregated.unsupported],
  );
  const unsupportedCount = unsupportedNodeIds.size;
  const autoConvertedNodes = Math.max(0, totalNodes - unsupportedCount);
  // Unique node ids that need any kind of review (unsupported, missing
  // generator, expression fallback, local path), deduped across formats.
  const reviewNodeCount = aggregated.manualReviewNodeCount;

  // ── 3-tier deploy status ─────────────────────────────────────────────────
  // Rule (single source of truth for the headline + counts):
  //   cannot_deploy → best-format generator failed, OR ≥1 unsupported tool,
  //                   OR an unsupported node sits in a disconnected component.
  //   ready         → coverage ≥ 95%, confidence ≥ 80, zero unsupported AND
  //                   zero review-level warnings (fallbacks / missing visitors).
  //   needs_review  → otherwise (best-format generator succeeded but there is
  //                   manual work to do).
  const allFailed =
    !bestFormat ||
    !Object.values(result.formats).some((fr) => fr.status === "success");
  // Derive deploy status from the full response (single source of truth —
  // see `deriveDeployStatus` for the rule table). Pure function; depends only
  // on `result`, so the memo key is just the response.
  const deployStatus: DeployStatus = useMemo(
    () => deriveDeployStatus(result),
    [result],
  );

  const { showWorkflowToggle, graphHeight } = useMemo(() => {
    if (!result.dag_data) return { showWorkflowToggle: false, graphHeight: 320 };
    const nodes = result.dag_data.nodes;
    const edges = result.dag_data.edges;
    const outDeg = new Map<number, number>();
    const inDeg = new Map<number, number>();
    for (const e of edges) {
      outDeg.set(e.source_id, (outDeg.get(e.source_id) ?? 0) + 1);
      inDeg.set(e.target_id, (inDeg.get(e.target_id) ?? 0) + 1);
    }
    const hasBranches =
      Array.from(outDeg.values()).some((c) => c > 1) ||
      Array.from(inDeg.values()).some((c) => c > 1);
    return {
      showWorkflowToggle: hasBranches || nodes.length > 8,
      graphHeight: Math.max(280, Math.min(560, nodes.length * 55)),
    };
  }, [result.dag_data]);

  const handleNodeSelect = (nodeId: number) => {
    if (!activeFormatResult) return;
    const match = findFileLineForNode(activeFormatResult.files, nodeId);
    if (!match) return;
    setActiveFile(activeFormatResult.files[match.fileIndex].filename);
    setHighlightLine(match.line);
    setTimeout(() => setHighlightLine(undefined), 1300);
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-6"
    >
      {/* ── Headline status banner ──────────────────────────────────── */}
      <DeployStatusBanner status={deployStatus} />

      {/* ── Counts row (under headline) ─────────────────────────────── */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <CountChip
          tone="success"
          value={`${autoConvertedNodes} of ${totalNodes} tools`}
          label="automatically converted"
        />
        <CountChip
          tone={reviewNodeCount > 0 ? "warning" : "muted"}
          value={`${reviewNodeCount} node${reviewNodeCount === 1 ? "" : "s"}`}
          label="need manual review"
        />
        <CountChip
          tone={
            bestCoverage === null
              ? "muted"
              : bestCoverage >= DEPLOY_THRESHOLDS.READY_COVERAGE
                ? "success"
                : bestCoverage >= 75
                  ? "warning"
                  : "destructive"
          }
          value={
            bestCoverage === null
              ? "—"
              : `${bestCoverage.toFixed(1)}% coverage`
          }
          label={`(best format: ${bestFormat ? formatLabel(bestFormat) : "n/a"})`}
        />
      </div>

      {/* Best format jump button (kept for parity with the prior UI) */}
      {!allFailed && bestFormatResult && activeFormat !== bestFormat && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--ring)]/30 bg-[var(--ring)]/5 px-4 py-3 text-sm text-[var(--fg)]">
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-[var(--ring)] shrink-0" />
            <span>
              Best format: <strong>{formatLabel(bestFormat)}</strong>
              {bestConfidence && (
                <span className="text-[var(--fg-muted)]">
                  {" "}({Math.round(bestConfidence.overall)}/100,{" "}
                  {bestConfidence.level})
                </span>
              )}
            </span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setActiveFormat(bestFormat)}
          >
            Jump to {formatLabel(bestFormat)} →
          </Button>
        </div>
      )}

      {/* ── Action bar ──────────────────────────────────────────────── */}
      <div className="flex items-center justify-end">
        <Button
          variant="secondary"
          size="sm"
          onClick={() =>
            downloadAllFormatsAsZip(result.formats, result.workflow_name)
          }
          disabled={allFailed}
        >
          <Download className="h-4 w-4" />
          Download all (zip)
        </Button>
      </div>

      {/* ── Metrics — full width, even columns ──────────────────────── */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <MetricCard
          label="Nodes"
          value={result.node_count}
          icon={<Network className="h-5 w-5" />}
        />
        <MetricCard
          label="Edges"
          value={result.edge_count}
          icon={<GitBranch className="h-5 w-5" />}
        />
        <MetricCard
          label="Files"
          value={totalFiles}
          icon={<FileCode className="h-5 w-5" />}
        />
        <MetricCard
          label="Coverage"
          value={bestCoverage ?? 0}
          suffix={bestCoverage !== null ? "%" : ""}
          icon={<Percent className="h-5 w-5" />}
        />
        {bestConfidence && (
          <MetricCard
            label="Confidence"
            value={Math.round(bestConfidence.overall)}
            suffix={`/100`}
            icon={<Shield className="h-5 w-5" />}
          />
        )}
      </div>

      {/* ── Categorized workflow warnings ───────────────────────────── */}
      <CategorizedWarningsView categorized={categorized} />

      {/* ── Performance hints (with severity legend tooltip) ────────── */}
      {hasPerfHints && (
        <div className="rounded-lg border border-blue-200 bg-blue-50/50 dark:border-blue-900 dark:bg-blue-950/30 p-4">
          <h4 className="mb-2 flex items-center gap-2 text-sm font-medium">
            <Zap className="h-4 w-4 text-blue-500" />
            Performance hints ({result.performance_hints!.length})
            <span
              className="ml-1 inline-flex items-center text-[var(--fg-muted)]"
              title={
                "Severity tells you how much the suggested change is likely " +
                "to matter:\n" +
                "high — significant cost, runtime, or correctness impact;\n" +
                "medium — noticeable improvement worth doing;\n" +
                "low — nice-to-have, mostly stylistic."
              }
            >
              <HelpCircle className="h-3.5 w-3.5" />
            </span>
          </h4>
          <div className="space-y-2">
            {result.performance_hints!.map(
              (h: PerformanceHint, i: number) => (
                <div key={i} className="flex items-start gap-2 text-sm">
                  <Badge
                    variant={
                      h.priority === "high"
                        ? "destructive"
                        : h.priority === "medium"
                          ? "secondary"
                          : "default"
                    }
                    className="mt-0.5 shrink-0 text-[10px]"
                  >
                    {h.priority}
                  </Badge>
                  <div>
                    <p>{h.suggestion}</p>
                    {h.code_snippet && (
                      <code className="mt-1 block rounded bg-muted px-2 py-1 text-xs">
                        {h.code_snippet}
                      </code>
                    )}
                  </div>
                </div>
              ),
            )}
          </div>
        </div>
      )}

      {/* ── View mode toggle ────────────────────────────────────────── */}
      {hasDag && showWorkflowToggle && (
        <div className="flex gap-1 rounded-lg bg-[var(--bg-sidebar)] p-1 w-fit">
          <button
            onClick={() => setViewMode("code")}
            className={cn(
              "px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
              viewMode === "code"
                ? "bg-[var(--bg-card)] text-[var(--fg)] shadow-sm"
                : "text-[var(--fg-muted)] hover:text-[var(--fg)]",
            )}
          >
            Code
          </button>
          <button
            onClick={() => setViewMode("workflow")}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
              viewMode === "workflow"
                ? "bg-[var(--bg-card)] text-[var(--fg)] shadow-sm"
                : "text-[var(--fg-muted)] hover:text-[var(--fg)]",
            )}
          >
            <Workflow className="h-3.5 w-3.5" />
            Workflow
          </button>
        </div>
      )}

      {/* ── Format tabs (outer) ─────────────────────────────────────── */}
      {(viewMode === "code" || !showWorkflowToggle) && (
        <Tabs value={activeFormat} onValueChange={setActiveFormat}>
          <TabsList>
            {FORMAT_ORDER.map((fmt) => {
              const fr = result.formats[fmt];
              const failed = fr?.status === "failed";
              const isBest = fmt === bestFormat;
              return (
                <TabsTrigger key={fmt} value={fmt}>
                  <span className="flex items-center gap-1.5">
                    <span
                      className={cn(
                        "inline-block h-2 w-2 rounded-full",
                        failed
                          ? "bg-destructive"
                          : fr?.status === "success"
                            ? "bg-success"
                            : "bg-[var(--fg-muted)]/40",
                      )}
                    />
                    {formatLabel(fmt)}
                    {isBest && !failed && (
                      <Badge
                        variant="success"
                        className="ml-1 text-[10px]"
                      >
                        Best
                      </Badge>
                    )}
                  </span>
                </TabsTrigger>
              );
            })}
            {hasExprAudit && (
              <TabsTrigger value="__expression_audit">
                <FileSearch className="mr-1 h-3.5 w-3.5" />
                Expressions
              </TabsTrigger>
            )}
          </TabsList>

          {FORMAT_ORDER.map((fmt) => {
            const fr = result.formats[fmt];
            return (
              <TabsContent key={fmt} value={fmt}>
                {!fr ? (
                  <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-6 text-sm text-[var(--fg-muted)]">
                    No result available for {formatLabel(fmt)}.
                  </div>
                ) : fr.status === "failed" ? (
                  <FailedFormatPanel
                    formatResult={fr}
                    workflowWarnings={result.warnings}
                  />
                ) : (
                  <SuccessFormatPanel
                    formatResult={fr}
                    workflowName={result.workflow_name}
                    workflowWarnings={result.warnings}
                    activeFile={activeFile}
                    onActiveFileChange={setActiveFile}
                    highlightLine={highlightLine}
                  />
                )}
              </TabsContent>
            );
          })}

          {hasExprAudit && (
            <TabsContent value="__expression_audit">
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/50">
                      <th className="p-3 text-left font-medium">Node</th>
                      <th className="p-3 text-left font-medium">Tool</th>
                      <th className="p-3 text-left font-medium">Field</th>
                      <th className="p-3 text-left font-medium">Expression</th>
                      <th className="p-3 text-left font-medium">Method</th>
                      <th className="p-3 text-right font-medium">
                        Confidence
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.expression_audit!.map(
                      (entry: ExpressionAuditEntry, i: number) => (
                        <tr key={i} className="border-b last:border-0">
                          <td className="p-3 font-mono text-xs">
                            {entry.node_id}
                          </td>
                          <td className="p-3">{entry.tool_type}</td>
                          <td className="p-3 font-mono text-xs">
                            {entry.field_name}
                          </td>
                          <td
                            className="max-w-[200px] truncate p-3 font-mono text-xs"
                            title={entry.original_expression}
                          >
                            {entry.original_expression}
                          </td>
                          <td className="p-3">
                            <Badge
                              variant={
                                entry.translation_method === "failed"
                                  ? "destructive"
                                  : "secondary"
                              }
                              className="text-[10px]"
                            >
                              {entry.translation_method}
                            </Badge>
                          </td>
                          <td className="p-3 text-right">
                            <span
                              className={cn(
                                "font-medium",
                                entry.confidence >= 0.8
                                  ? "text-green-600"
                                  : entry.confidence >= 0.5
                                    ? "text-yellow-600"
                                    : "text-red-600",
                              )}
                            >
                              {(entry.confidence * 100).toFixed(0)}%
                            </span>
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </TabsContent>
          )}
        </Tabs>
      )}

      {/* ── Workflow split view ─────────────────────────────────────── */}
      {viewMode === "workflow" &&
        hasDag &&
        showWorkflowToggle &&
        activeFormatResult && (
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
            <div
              className="lg:col-span-3 rounded-xl border border-[var(--border)] overflow-hidden"
              style={{ height: graphHeight }}
            >
              <WorkflowGraph
                dagData={result.dag_data!}
                onNodeSelect={handleNodeSelect}
              />
            </div>
            <div className="lg:col-span-2 space-y-3">
              <Tabs value={activeFormat} onValueChange={setActiveFormat}>
                <TabsList>
                  {FORMAT_ORDER.map((fmt) => {
                    const fr = result.formats[fmt];
                    const failed = fr?.status === "failed";
                    return (
                      <TabsTrigger key={fmt} value={fmt}>
                        <span className="flex items-center gap-1.5">
                          <span
                            className={cn(
                              "inline-block h-2 w-2 rounded-full",
                              failed
                                ? "bg-destructive"
                                : fr?.status === "success"
                                  ? "bg-success"
                                  : "bg-[var(--fg-muted)]/40",
                            )}
                          />
                          {formatLabel(fmt)}
                        </span>
                      </TabsTrigger>
                    );
                  })}
                </TabsList>
              </Tabs>
              {activeFormatResult.status === "failed" ? (
                <FailedFormatPanel
                  formatResult={activeFormatResult}
                  workflowWarnings={result.warnings}
                />
              ) : (
                <Tabs value={activeFile} onValueChange={setActiveFile}>
                  <TabsList>
                    {activeFormatResult.files.map((f) => (
                      <TabsTrigger key={f.filename} value={f.filename}>
                        {f.filename}
                      </TabsTrigger>
                    ))}
                  </TabsList>
                  {activeFormatResult.files.map((f) => (
                    <TabsContent key={f.filename} value={f.filename}>
                      <CodeBlock
                        code={f.content}
                        language={f.file_type}
                        filename={f.filename}
                        highlightLine={
                          f.filename === activeFile ? highlightLine : undefined
                        }
                      />
                    </TabsContent>
                  ))}
                </Tabs>
              )}
            </div>
          </div>
        )}
    </motion.div>
  );
}

// ── Headline banner ────────────────────────────────────────────────────────
function DeployStatusBanner({ status }: { status: DeployStatus }) {
  if (status === "ready") {
    return (
      <div className="flex items-start gap-3 rounded-lg border border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950/30 px-4 py-3 text-sm text-green-800 dark:text-green-200">
        <CheckCircle className="mt-0.5 h-5 w-5 shrink-0" />
        <div>
          <div className="font-semibold">Ready to deploy</div>
          <div className="text-green-700/80 dark:text-green-300/80">
            Every Alteryx tool was converted, coverage is high, and confidence
            is strong. You can run the generated code as-is.
          </div>
        </div>
      </div>
    );
  }
  if (status === "needs_review") {
    return (
      <div className="flex items-start gap-3 rounded-lg border border-yellow-200 bg-yellow-50 dark:border-yellow-900 dark:bg-yellow-950/30 px-4 py-3 text-sm text-yellow-800 dark:text-yellow-200">
        <Info className="mt-0.5 h-5 w-5 shrink-0" />
        <div>
          <div className="font-semibold">Needs review before deploy</div>
          <div className="text-yellow-700/80 dark:text-yellow-300/80">
            The conversion produced runnable code, but a2d emitted best-effort
            translations or fallback comments for some nodes. Review the
            warnings below — once you fix them you can deploy.
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/30 px-4 py-3 text-sm text-red-800 dark:text-red-200">
      <Ban className="mt-0.5 h-5 w-5 shrink-0" />
      <div>
        <div className="font-semibold">Cannot deploy as-is</div>
        <div className="text-red-700/80 dark:text-red-300/80">
          One or more tools couldn't be converted, or the generator failed
          outright. The dataflow is incomplete — see the “Cannot convert”
          warnings below for the nodes you'll need to rewrite by hand.
        </div>
      </div>
    </div>
  );
}

// ── Counts row chip ────────────────────────────────────────────────────────
function CountChip({
  tone,
  value,
  label,
}: {
  tone: "success" | "warning" | "muted" | "destructive";
  value: string;
  label: string;
}) {
  const toneClass =
    tone === "success"
      ? "border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950/30"
      : tone === "warning"
        ? "border-yellow-200 bg-yellow-50 dark:border-yellow-900 dark:bg-yellow-950/30"
        : tone === "destructive"
          ? "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/30"
          : "border-[var(--border)] bg-[var(--bg-card)]";
  return (
    <div className={cn("rounded-lg border px-4 py-3", toneClass)}>
      <div className="text-base font-semibold text-[var(--fg)]">{value}</div>
      <div className="text-xs text-[var(--fg-muted)]">{label}</div>
    </div>
  );
}

// ── Categorized warnings ───────────────────────────────────────────────────
function CategorizedWarningsView({
  categorized,
}: {
  categorized: CategorizedWarnings;
}) {
  if (categorized.total === 0) return null;
  return (
    <div className="space-y-3">
      <WarningGroup
        accent="destructive"
        icon={<Ban className="h-4 w-4" />}
        title="Cannot convert"
        explanation="a2d doesn't yet support these Alteryx tools. The generated code skips them — you must replace these manually."
        warnings={categorized.unsupported}
      />
      <WarningGroup
        accent="warning"
        icon={<AlertTriangle className="h-4 w-4" />}
        title="Manual review needed"
        explanation="a2d emitted a best-effort translation, but you should verify the logic before running."
        warnings={categorized.review}
      />
      <WarningGroup
        accent="info"
        icon={<Info className="h-4 w-4" />}
        title="Graph structure note"
        explanation="Your workflow has multiple independent dataflows. This is normal in complex workflows but means some nodes don't feed into a final output."
        warnings={categorized.graph}
      />
      <WarningGroup
        accent="muted"
        icon={<HelpCircle className="h-4 w-4" />}
        title="Other warnings"
        explanation="Less common warnings without a structured template — shown verbatim."
        warnings={categorized.other}
      />
    </div>
  );
}

function WarningGroup({
  accent,
  icon,
  title,
  explanation,
  warnings,
}: {
  accent: "destructive" | "warning" | "info" | "muted";
  icon: React.ReactNode;
  title: string;
  explanation: string;
  warnings: ParsedWarning[];
}) {
  const [open, setOpen] = useState(accent === "destructive");
  if (warnings.length === 0) return null;

  const toneClass =
    accent === "destructive"
      ? "border-red-200 bg-red-50/50 dark:border-red-900 dark:bg-red-950/20 text-red-900 dark:text-red-200"
      : accent === "warning"
        ? "border-yellow-200 bg-yellow-50/50 dark:border-yellow-900 dark:bg-yellow-950/20 text-yellow-900 dark:text-yellow-200"
        : accent === "info"
          ? "border-blue-200 bg-blue-50/50 dark:border-blue-900 dark:bg-blue-950/20 text-blue-900 dark:text-blue-200"
          : "border-[var(--border)] bg-[var(--bg-card)] text-[var(--fg)]";

  return (
    <Collapsible.Root open={open} onOpenChange={setOpen}>
      <div className={cn("rounded-lg border", toneClass)}>
        <Collapsible.Trigger className="flex w-full items-start gap-3 px-4 py-3 text-left text-sm">
          <span className="mt-0.5 shrink-0">{icon}</span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 font-medium">
              {title}
              <Badge
                variant={
                  accent === "destructive"
                    ? "destructive"
                    : accent === "warning"
                      ? "warning"
                      : "secondary"
                }
                className="text-[10px]"
              >
                {warnings.length}
              </Badge>
            </div>
            <div className="mt-0.5 text-xs opacity-80">{explanation}</div>
          </div>
          <ChevronDown
            className={cn(
              "mt-0.5 h-4 w-4 shrink-0 transition-transform",
              open && "rotate-180",
            )}
          />
        </Collapsible.Trigger>
        <Collapsible.Content>
          <AnimatePresence>
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              className="space-y-1.5 border-t border-current/10 px-4 py-3"
            >
              {warnings.map((w, i) => (
                <ParsedWarningItem key={i} warning={w} />
              ))}
            </motion.div>
          </AnimatePresence>
        </Collapsible.Content>
      </div>
    </Collapsible.Root>
  );
}

function ParsedWarningItem({ warning }: { warning: ParsedWarning }) {
  return (
    <div className="rounded-md bg-[var(--bg-card)]/50 px-3 py-2 text-xs text-[var(--fg)] border border-current/10">
      <div className="font-medium text-[var(--fg)]">{warning.title}</div>
      <div className="mt-0.5 text-[var(--fg-muted)]">{warning.detail}</div>
      {warning.kind === "other" && (
        <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px] text-[var(--fg-muted)]">
          {warning.raw}
        </pre>
      )}
    </div>
  );
}

// ── Failed format panel ────────────────────────────────────────────────────
function FailedFormatPanel({
  formatResult,
  workflowWarnings,
}: {
  formatResult: FormatResult;
  workflowWarnings: ReadonlyArray<string>;
}) {
  const categorized = useMemo(
    () => categorizeForFormat(workflowWarnings, formatResult.warnings),
    [workflowWarnings, formatResult.warnings],
  );
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 space-y-4">
      <div className="flex items-center gap-2 text-sm font-medium text-destructive">
        <XCircle className="h-4 w-4 shrink-0" />
        {formatLabel(formatResult.format)} conversion failed
      </div>
      {formatResult.error && (
        <pre className="whitespace-pre-wrap break-words rounded-md border border-destructive/20 bg-[var(--bg-card)] p-3 font-mono text-xs text-[var(--fg)]">
          {formatResult.error}
        </pre>
      )}
      <CategorizedWarningsView categorized={categorized} />
    </div>
  );
}

interface SuccessFormatPanelProps {
  formatResult: FormatResult;
  workflowName: string;
  workflowWarnings: ReadonlyArray<string>;
  activeFile: string | undefined;
  onActiveFileChange: (filename: string) => void;
  highlightLine: number | undefined;
}

function SuccessFormatPanel({
  formatResult,
  workflowName,
  workflowWarnings,
  activeFile,
  onActiveFileChange,
  highlightLine,
}: SuccessFormatPanelProps) {
  const confidence = formatResult.confidence;
  const coverage = formatResult.stats.coverage_percentage;
  const fallbackFile = formatResult.files[0]?.filename;
  const currentFile =
    activeFile && formatResult.files.some((f) => f.filename === activeFile)
      ? activeFile
      : fallbackFile;

  // Per-format warnings get the same parser/grouping as workflow-level ones
  // so the user sees consistent copy on every tab.
  const categorized = useMemo(
    () => categorizeForFormat(workflowWarnings, formatResult.warnings),
    [workflowWarnings, formatResult.warnings],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-4 py-2.5 text-sm">
        <div className="flex flex-wrap items-center gap-2 text-[var(--fg-muted)]">
          {confidence && (
            <Badge
              variant={
                confidence.level === "High"
                  ? "success"
                  : confidence.level === "Medium"
                    ? "warning"
                    : "destructive"
              }
            >
              Confidence: {confidence.level} (
              {Math.round(confidence.overall)}/100)
            </Badge>
          )}
          {typeof coverage === "number" && (
            <span>
              Coverage:{" "}
              <strong className="text-[var(--fg)]">
                {coverage.toFixed(1)}%
              </strong>
            </span>
          )}
          <span>
            {formatResult.files.length} file
            {formatResult.files.length === 1 ? "" : "s"}
          </span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => downloadFormatAsZip(formatResult, workflowName)}
        >
          <Download className="h-4 w-4" />
          Download {formatLabel(formatResult.format)}.zip
        </Button>
      </div>

      <CategorizedWarningsView categorized={categorized} />

      {currentFile ? (
        <Tabs value={currentFile} onValueChange={onActiveFileChange}>
          <TabsList>
            {formatResult.files.map((f) => (
              <TabsTrigger key={f.filename} value={f.filename}>
                {f.filename}
                <Badge variant="secondary" className="ml-2 text-[10px]">
                  {f.file_type}
                </Badge>
              </TabsTrigger>
            ))}
          </TabsList>
          {formatResult.files.map((f) => (
            <TabsContent key={f.filename} value={f.filename}>
              <CodeBlock
                code={f.content}
                language={f.file_type}
                filename={f.filename}
                highlightLine={f.filename === currentFile ? highlightLine : undefined}
              />
            </TabsContent>
          ))}
        </Tabs>
      ) : (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-6 text-sm text-[var(--fg-muted)]">
          No files generated.
        </div>
      )}
    </div>
  );
}

// Used by the previous version; kept exported so other components could rely
// on a stable shape if needed in the future.
export type { CategorizedWarnings, ParsedWarning };

// Suppress "TriangleAlert imported but unused" while still allowing rapid
// re-introduction of the old banner if a designer asks for it.
void TriangleAlert;
