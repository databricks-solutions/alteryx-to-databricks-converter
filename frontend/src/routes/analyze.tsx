import { useEffect } from "react";
import { useNavigate } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/page-header";
import { FileDropzone } from "@/components/shared/file-dropzone";
import { MetricCard } from "@/components/shared/metric-card";
import { WorkflowTable } from "@/components/analyze/workflow-table";
import { AnalysisSummary } from "@/components/analyze/analysis-summary";
import { ToolFrequency } from "@/components/analyze/tool-frequency";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnalysis } from "@/hooks/use-analysis";
import { useEstateStore, isStale } from "@/stores/estate";
import { useConvertBridge } from "@/stores/convert-bridge";
import { downloadAnalysisCSV } from "@/lib/csv";
import { motion } from "motion/react";
import type { AnalysisResult } from "@/lib/api";
import {
  ArrowRight,
  BarChart3,
  Loader2,
  FileText,
  Network,
  Gauge,
  Download,
  AlertTriangle,
  RotateCcw,
} from "lucide-react";

export function AnalyzePage({ embedded = false }: { embedded?: boolean }) {
  const files = useEstateStore((s) => s.files);
  const setFiles = useEstateStore((s) => s.setFiles);
  const stored = useEstateStore((s) => s.results.analyze);
  const saveResult = useEstateStore((s) => s.saveResult);
  const clearResult = useEstateStore((s) => s.clearResult);
  const mutation = useAnalysis();
  const setBridgeWorkflow = useConvertBridge((s) => s.setWorkflowName);
  const navigate = useNavigate();

  // Persist successful analysis results to the shared estate store.
  useEffect(() => {
    if (mutation.data) saveResult("analyze", mutation.data);
  }, [mutation.data, saveResult]);

  // Fresh result wins; otherwise fall back to the persisted one so navigating
  // away and back (or reloading) doesn't discard the report.
  const displayData: AnalysisResult | null = mutation.data ?? stored?.data ?? null;
  const staleResult = !mutation.data && isStale(stored, files);

  const handleAnalyze = () => {
    if (files.length === 0) return;
    mutation.mutate(files);
  };

  const handleNewAnalysis = () => {
    mutation.reset();
    clearResult("analyze");
  };

  const actions = displayData ? (
    <div className="flex items-center gap-2">
      <Button
        variant="secondary"
        size="sm"
        onClick={() => downloadAnalysisCSV(displayData.workflows)}
      >
        <Download className="h-4 w-4" />
        Export CSV
      </Button>
      <Button variant="ghost" size="sm" onClick={handleNewAnalysis}>
        <RotateCcw className="h-4 w-4" />
        New Analysis
      </Button>
    </div>
  ) : null;

  return (
    <div className="space-y-6">
      {!embedded && (
        <PageHeader
          title="Analyze Workflows"
          description="Upload Alteryx files (.yxmd, .yxmc, .yxwz, or .yxzp packages) to assess migration readiness and complexity"
        >
          {actions}
        </PageHeader>
      )}
      {embedded && actions && <div className="flex justify-end">{actions}</div>}

      {!embedded && (
        <p className="text-xs text-[var(--fg-muted)] -mt-2 mb-4">
          Note: this profiles workflow footprint and complexity (tools, coverage, structure, dependencies). It does not
          measure data volumes or row counts, which depend on the source systems.
        </p>
      )}

      {staleResult && (
        <p className="text-xs text-[var(--fg-muted)]">
          Showing a report from a previously loaded estate — click Generate Report to refresh for the current files.
        </p>
      )}

      {!displayData && (
        <>
          <FileDropzone files={files} onFilesChange={setFiles} multiple />

          <div className="flex items-center gap-3">
            <Button
              onClick={handleAnalyze}
              disabled={files.length === 0 || mutation.isPending}
            >
              {mutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <BarChart3 className="h-4 w-4" />
              )}
              Generate Report
            </Button>
          </div>
        </>
      )}

      {mutation.isPending && (
        <div className="space-y-4">
          <div className="text-sm text-[var(--fg-muted)] animate-pulse">
            Analyzing {files.length} workflow{files.length > 1 ? "s" : ""}...
          </div>
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      )}

      {mutation.error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <p className="font-medium mb-1">Analysis failed</p>
          <p>{mutation.error.message}</p>
          <div className="mt-2 text-xs text-destructive/70 space-y-1">
            {mutation.error.message.includes("Failed to fetch") && (
              <p>Check that the API server is running and accessible.</p>
            )}
            {mutation.error.message.includes("422") && (
              <p>The uploaded file may not be a valid Alteryx file (.yxmd, .yxmc, .yxwz, or .yxzp package).</p>
            )}
          </div>
          <Button variant="ghost" size="sm" className="mt-2" onClick={handleAnalyze}>
            Retry
          </Button>
        </div>
      )}

      {displayData && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="space-y-6"
        >
          {/* Plain-English summary */}
          <AnalysisSummary data={displayData} />

          {/* Summary */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              label="Workflows"
              value={displayData.total_workflows}
              icon={<FileText className="h-5 w-5" />}
            />
            <MetricCard
              label="Total Nodes"
              value={displayData.total_nodes}
              icon={<Network className="h-5 w-5" />}
            />
            <MetricCard
              label="Avg Coverage"
              value={displayData.avg_coverage}
              suffix="%"
              icon={<BarChart3 className="h-5 w-5" />}
            />
            <MetricCard
              label="Avg Complexity"
              value={displayData.avg_complexity}
              icon={<Gauge className="h-5 w-5" />}
            />
          </div>

          {/* Unsupported tools alert */}
          {displayData.unsupported_tools.length > 0 && (
            <Card className="border-warning/30 bg-warning/5">
              <div className="flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 text-warning shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-[var(--fg)]">
                    {displayData.unsupported_tools.length} unsupported tool type{displayData.unsupported_tools.length > 1 ? "s" : ""} detected
                  </p>
                  <p className="text-xs text-[var(--fg-muted)] mt-1 mb-2">
                    These tools require manual migration. Generated code will include placeholder scaffolding.
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {displayData.unsupported_tools.map((t) => (
                      <Badge key={t} variant="destructive">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>
            </Card>
          )}

          {/* Table with sorting/filter */}
          <WorkflowTable workflows={displayData.workflows} />

          {/* Charts */}
          <ToolFrequency data={displayData.tool_frequency} />

          {/* Next steps */}
          <Card>
            <h3 className="text-sm font-semibold text-[var(--fg)] mb-2">Next Steps</h3>
            <ul className="text-sm text-[var(--fg-muted)] space-y-1 list-disc list-inside">
              <li>Start with High priority / Low effort workflows for quick wins</li>
              <li>Review unsupported tools and plan manual migration approach</li>
              <li>Use the Convert page to generate Databricks code for each workflow</li>
            </ul>
            <Button
              size="sm"
              className="mt-3"
              onClick={() => {
                if (displayData?.workflows?.[0]) {
                  setBridgeWorkflow(displayData.workflows[0].workflow_name);
                }
                navigate({ to: "/convert" });
              }}
            >
              Go to Convert <ArrowRight className="h-4 w-4 ml-1" />
            </Button>
          </Card>
        </motion.div>
      )}
    </div>
  );
}
