import { useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { FileDropzone } from "@/components/shared/file-dropzone";
import { MetricCard } from "@/components/shared/metric-card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { usePortfolio } from "@/hooks/use-insights";
import { downloadJson } from "@/lib/portfolio-download";
import { Play, Loader2, RotateCcw, Download, Layers, GitBranch, Copy, Clock } from "lucide-react";

const EFFORT_VARIANT: Record<string, "success" | "warning" | "destructive" | "secondary"> = {
  Low: "success",
  Medium: "warning",
  High: "destructive",
};

export function PortfolioPage() {
  const [files, setFiles] = useState<File[]>([]);
  const mutation = usePortfolio();
  const report = mutation.data;

  const handleAnalyze = () => {
    if (files.length === 0) return;
    mutation.mutate({ files });
  };

  const handleReset = () => {
    mutation.reset();
    setFiles([]);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Portfolio Analysis"
        description="Analyze a whole estate at once — cross-workflow dependencies, shared macros, duplicated logic, and a migration-wave plan"
      >
        {report && (
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => downloadJson(report, "portfolio-analysis.json")}
            >
              <Download className="h-4 w-4" />
              Export JSON
            </Button>
            <Button variant="secondary" size="sm" onClick={handleReset}>
              <RotateCcw className="h-4 w-4" />
              New Analysis
            </Button>
          </>
        )}
      </PageHeader>

      {!report && (
        <div className="space-y-4">
          <p className="text-sm text-[var(--fg-muted)]">
            Upload several workflows together — the value is in the cross-workflow view, so the more of
            your estate you include, the more useful the dependency graph and wave plan become.
          </p>
          <FileDropzone files={files} onFilesChange={setFiles} multiple />
          <Button onClick={handleAnalyze} disabled={files.length === 0 || mutation.isPending}>
            {mutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            Analyze Estate
          </Button>
          {mutation.isError && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              {mutation.error.message}
            </div>
          )}
        </div>
      )}

      {report && (
        <div className="space-y-6">
          {/* Estate rollup */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard label="WORKFLOWS" value={report.summary.workflow_count} />
            <MetricCard label="DEPENDENCIES" value={report.summary.dependency_count} />
            <MetricCard label="WAVES" value={report.summary.wave_count} />
            <MetricCard
              label="EST. EFFORT"
              value={report.summary.estimated_effort_days}
              suffix=" days"
            />
          </div>

          {/* Migration wave plan — the headline output */}
          <Card className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <Layers className="h-4 w-4 text-[var(--ring)]" />
              <h2 className="text-sm font-semibold text-[var(--fg)]">Migration wave plan</h2>
              <span className="text-xs text-[var(--fg-muted)]">
                ordered by value x readiness / effort, respecting dependencies
              </span>
            </div>
            {report.migration_plan.waves.length === 0 ? (
              <p className="text-sm text-[var(--fg-muted)]">No waves produced.</p>
            ) : (
              <div className="space-y-4">
                {report.migration_plan.waves.map((wave) => (
                  <div key={wave.wave}>
                    <div className="flex items-center gap-2 mb-1.5">
                      <Badge>Wave {wave.wave}</Badge>
                      <span className="text-xs text-[var(--fg-muted)]">
                        ~{wave.estimated_effort_days} person-days · {wave.workflows.length} workflow(s)
                      </span>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs border-collapse">
                        <thead>
                          <tr className="text-[var(--fg-muted)] text-left">
                            <th className="py-1 pr-3 font-medium">Workflow</th>
                            <th className="py-1 pr-3 font-medium text-right">Score</th>
                            <th className="py-1 pr-3 font-medium text-right">Coverage</th>
                            <th className="py-1 pr-3 font-medium text-right">Nodes</th>
                            <th className="py-1 pr-3 font-medium">Effort</th>
                            <th className="py-1 pr-3 font-medium">Depends on</th>
                          </tr>
                        </thead>
                        <tbody>
                          {wave.workflows.map((w) => (
                            <tr key={w.workflow_name} className="border-t border-[var(--border)]">
                              <td className="py-1.5 pr-3 font-medium text-[var(--fg)]">
                                {w.workflow_name}
                              </td>
                              <td className="py-1.5 pr-3 text-right">{w.score.toFixed(1)}</td>
                              <td className="py-1.5 pr-3 text-right">{w.coverage_pct.toFixed(0)}%</td>
                              <td className="py-1.5 pr-3 text-right">{w.node_count}</td>
                              <td className="py-1.5 pr-3">
                                <Badge variant={EFFORT_VARIANT[w.estimated_effort] ?? "secondary"}>
                                  {w.estimated_effort}
                                </Badge>
                              </td>
                              <td className="py-1.5 pr-3 text-[var(--fg-muted)]">
                                {w.depends_on.length > 0 ? w.depends_on.join(", ") : "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Cross-workflow dependencies */}
          {report.dependencies.length > 0 && (
            <Card className="p-4">
              <div className="flex items-center gap-2 mb-3">
                <GitBranch className="h-4 w-4 text-[var(--ring)]" />
                <h2 className="text-sm font-semibold text-[var(--fg)]">
                  Cross-workflow dependencies
                </h2>
              </div>
              <div className="space-y-1.5 text-xs">
                {report.dependencies.map((d, i) => (
                  <div key={i} className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-[var(--fg)]">{d.producer}</span>
                    <span className="text-[var(--fg-muted)]">→</span>
                    <span className="font-medium text-[var(--fg)]">{d.consumer}</span>
                    <span className="text-[var(--fg-muted)]">via {d.artifact}</span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Consolidation opportunities */}
          {(report.shared_macros.length > 0 || report.duplicate_subflows.length > 0) && (
            <Card className="p-4">
              <div className="flex items-center gap-2 mb-3">
                <Copy className="h-4 w-4 text-[var(--ring)]" />
                <h2 className="text-sm font-semibold text-[var(--fg)]">
                  Consolidation opportunities
                </h2>
                <span className="text-xs text-[var(--fg-muted)]">migrate once, reuse everywhere</span>
              </div>
              <div className="space-y-2 text-xs">
                {report.shared_macros.map((m) => (
                  <div key={m.macro_path}>
                    <span className="font-medium text-[var(--fg)]">{m.macro_path}</span>{" "}
                    <span className="text-[var(--fg-muted)]">
                      used by {m.usage_count}: {m.used_by.join(", ")}
                    </span>
                  </div>
                ))}
                {report.duplicate_subflows.map((d) => (
                  <div key={d.fingerprint}>
                    <span className="font-medium text-[var(--fg)]">{d.description}</span>{" "}
                    <span className="text-[var(--fg-muted)]">
                      {d.occurrence_count} copies in {d.found_in.join(", ")}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {report.isolated_workflows.length > 0 && (
            <div className="flex items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 text-xs text-[var(--fg-muted)]">
              <Clock className="h-4 w-4 shrink-0 mt-0.5" />
              <span>
                <strong className="text-[var(--fg)]">
                  {report.isolated_workflows.length} standalone workflow(s)
                </strong>{" "}
                share no data or macros with the rest — they can be migrated in any order:{" "}
                {report.isolated_workflows.join(", ")}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
