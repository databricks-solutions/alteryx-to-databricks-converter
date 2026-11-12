import { MetricCard } from "@/components/shared/metric-card";
import { WorkflowTable } from "@/components/analyze/workflow-table";
import { AnalysisSummary } from "@/components/analyze/analysis-summary";
import { ToolFrequency } from "@/components/analyze/tool-frequency";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { useEstateView } from "@/hooks/use-estate-view";
import { api, type WorkflowAnalysisSummary } from "@/lib/api";
import { motion } from "motion/react";
import { BarChart3, FileText, Network, Gauge, AlertTriangle } from "lucide-react";

/** The per-workflow readiness report for the open project. Runs by itself. */
export function AnalyzePage() {
  const view = useEstateView({
    kind: "analyze",
    run: (source) => api.analyze(source),
    auto: true,
    onResult: (data, ctx) => {
      const byName: Record<string, WorkflowAnalysisSummary> = {};
      for (const w of data.workflows) {
        byName[w.source_file_name ?? w.file_name] = {
          coverage_percentage: w.coverage_percentage,
          complexity_score: w.complexity_score,
          complexity_level: w.complexity_level,
          migration_priority: w.migration_priority,
          estimated_effort: w.estimated_effort,
        };
      }
      ctx.afterEstatePass({ assessed: true, analysis: byName });
    },
  });
  const displayData = view.data;

  return (
    <div className="space-y-6">
      <p className="text-xs text-[var(--fg-muted)]">
        Profiles workflow footprint and complexity (tools, coverage, structure). It doesn't measure data volumes or
        row counts, which depend on the source systems.
      </p>

      {view.isPending && (
        <div className="space-y-4" role="status" aria-live="polite">
          <div className="text-sm text-[var(--fg-muted)] animate-pulse">
            Analyzing {view.ctx.workflows.length} workflow{view.ctx.workflows.length === 1 ? "" : "s"}…
          </div>
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      )}

      {view.error && !view.isPending && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <p className="font-medium mb-1">Analysis failed</p>
          <p>{view.error.message}</p>
          <Button variant="ghost" size="sm" className="mt-2" onClick={() => view.rerun()}>
            Try again
          </Button>
        </div>
      )}

      {displayData && !view.isPending && (
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

        </motion.div>
      )}
    </div>
  );
}
