import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { PageHeader } from "@/components/layout/page-header";
import { FileDropzone } from "@/components/shared/file-dropzone";
import { MetricCard } from "@/components/shared/metric-card";
import { ToolDifficulty, DifficultyDistribution } from "@/components/assess/tool-difficulty";
import { ProfilerSettings } from "@/components/assess/profiler-settings";
import { tierColor } from "@/components/assess/tier-meta";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAssess, useAssessDefaults } from "@/hooks/use-assess";
import type { AssessResult } from "@/lib/api";
import {
  Workflow,
  Boxes,
  Shapes,
  Database,
  Braces,
  Ruler,
  Download,
  RotateCcw,
  Loader2,
  Clock,
} from "lucide-react";

function downloadBlob(filename: string, content: string, mime: string) {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function toCsv(result: AssessResult): string {
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
  // RFC-4180 quoting: workflow names can contain commas, quotes, or newlines,
  // which would otherwise shift columns or corrupt the export.
  const esc = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;
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
      .map(esc)
      .join(","),
  );
  return [header.map(esc).join(","), ...rows].join("\n");
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-[var(--border)] py-2 last:border-0">
      <span className="text-xs text-[var(--fg-muted)]">{label}</span>
      <span className="text-sm font-medium tabular-nums text-[var(--fg)]">{value}</span>
    </div>
  );
}

export function AssessPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [hours, setHours] = useState(false);
  const [categoryTiers, setCategoryTiers] = useState<Record<string, string>>({});
  const [toolOverrides, setToolOverrides] = useState<Record<string, string>>({});
  const mutation = useAssess();
  const { data: defaults } = useAssessDefaults();
  const result = mutation.data;

  // Seed the tier editor from the server defaults once they arrive.
  useEffect(() => {
    if (defaults && Object.keys(categoryTiers).length === 0) {
      setCategoryTiers({ ...defaults.category_tiers });
    }
  }, [defaults, categoryTiers]);

  const runProfile = () => {
    if (files.length === 0) return;
    // Only send overrides that differ from the server defaults.
    const categoryChanged =
      defaults &&
      Object.keys(categoryTiers).some((c) => categoryTiers[c] !== defaults.category_tiers[c]);
    const config: Record<string, unknown> = {};
    if (categoryChanged) config.category_tiers = categoryTiers;
    if (Object.keys(toolOverrides).length > 0) config.tool_overrides = toolOverrides;
    mutation.mutate({ files, hours, config: Object.keys(config).length ? config : undefined });
  };

  const reset = () => {
    setFiles([]);
    mutation.reset();
    // Also clear customized profiler settings so a fresh run starts from the
    // defaults rather than silently reusing the previous run's assumptions.
    // categoryTiers re-seeds from server defaults via the effect above.
    setHours(false);
    setCategoryTiers({});
    setToolOverrides({});
  };

  return (
    <div>
      <PageHeader
        title="Migration Profiler"
        description="Profile an Alteryx estate: footprint, complexity, and tool-by-difficulty breakdown"
      >
        {result && (
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => downloadBlob("migration_profile.csv", toCsv(result), "text/csv")}
            >
              <Download className="h-4 w-4" />
              CSV
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() =>
                downloadBlob("migration_profile.json", JSON.stringify(result, null, 2), "application/json")
              }
            >
              <Download className="h-4 w-4" />
              JSON
            </Button>
            <Button variant="ghost" size="sm" onClick={reset}>
              <RotateCcw className="h-4 w-4" />
              New
            </Button>
          </>
        )}
      </PageHeader>

      <p className="text-xs text-[var(--fg-muted)] -mt-4 mb-6">
        Note: this profiles workflow footprint and complexity (tools, coverage, structure, dependencies). It does not
        measure data volumes or row counts, which depend on the source systems.
      </p>

      {/* Upload */}
      {!result && !mutation.isPending && (
        <Card className="flex flex-col gap-5">
          <FileDropzone files={files} onFilesChange={setFiles} multiple />

          <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-[var(--border)] p-3">
            <input
              type="checkbox"
              checked={hours}
              onChange={(e) => setHours(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-[var(--ring)]"
            />
            <span className="text-sm text-[var(--fg)]">
              Include effort estimate (hours)
              <span className="mt-0.5 block text-xs text-[var(--fg-muted)]">
                Model-based estimate from per-tier anchors. Off by default — treat any hours as indicative, not a quote.
              </span>
            </span>
          </label>

          {defaults && (
            <ProfilerSettings
              defaults={defaults}
              value={categoryTiers}
              onChange={setCategoryTiers}
              toolOverrides={toolOverrides}
              onToolOverridesChange={setToolOverrides}
            />
          )}

          <div className="flex items-center gap-3">
            <Button onClick={runProfile} disabled={files.length === 0}>
              <Ruler className="h-4 w-4" />
              Profile estate
            </Button>
            {files.length > 0 && (
              <span className="text-xs text-[var(--fg-muted)]">
                {files.length} file{files.length === 1 ? "" : "s"} selected
              </span>
            )}
          </div>

          {mutation.isError && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-500">
              <p className="font-medium">Profiling failed</p>
              <p className="mt-1 text-[var(--fg-muted)]">{mutation.error.message}</p>
            </div>
          )}
        </Card>
      )}

      {/* Loading */}
      {mutation.isPending && (
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-2 text-sm text-[var(--fg-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            Profiling {files.length} workflow{files.length === 1 ? "" : "s"}…
          </div>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-48" />
        </div>
      )}

      {/* Results */}
      {result && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="flex flex-col gap-6"
        >
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <MetricCard label="Workflows" value={result.totals.workflows} icon={<Workflow className="h-5 w-5" />} />
            <MetricCard label="Tools" value={result.totals.tools} icon={<Boxes className="h-5 w-5" />} hint="Total nodes across the estate" />
            <MetricCard label="Unique tool types" value={result.totals.unique_tool_types} icon={<Shapes className="h-5 w-5" />} />
            <MetricCard label="Data sources" value={result.totals.data_sources} icon={<Database className="h-5 w-5" />} hint="Input/source tool instances" />
          </div>

          <ToolDifficulty counts={result.tool_difficulty.counts} types={result.tool_difficulty.types} />

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <DifficultyDistribution distribution={result.difficulty_distribution} />

            <Card className="flex flex-col gap-3">
              <div>
                <h2 className="text-sm font-semibold text-[var(--fg)]">Estate Footprint</h2>
                <p className="text-xs text-[var(--fg-muted)] mt-0.5">Size and shape of the workflows</p>
              </div>
              <div>
                <StatRow label="Avg tools / workflow" value={result.size_distribution.avg_tools_per_workflow.toFixed(1)} />
                <StatRow
                  label="Largest workflow"
                  value={`${result.size_distribution.max_tools} tools (${result.size_distribution.max_tools_workflow})`}
                />
                <StatRow label="Avg DAG depth" value={result.size_distribution.avg_dag_depth.toFixed(1)} />
                <StatRow
                  label="Deepest workflow"
                  value={`${result.size_distribution.max_dag_depth} (${result.size_distribution.max_dag_depth_workflow})`}
                />
                <StatRow label="Connections" value={String(result.totals.connections)} />
                <StatRow label="Expressions" value={String(result.totals.expressions)} />
                <StatRow label="Workflows with macros" value={String(result.totals.workflows_with_macros)} />
              </div>
            </Card>
          </div>

          {result.total_hours != null && (
            <Card className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-[var(--ring)]" />
                <h2 className="text-sm font-semibold text-[var(--fg)]">Estimated Effort</h2>
              </div>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <p className="text-2xl font-bold text-[var(--fg)]">~{Math.round(result.total_hours)}</p>
                  <p className="text-xs text-[var(--fg-muted)]">hours</p>
                </div>
                <div>
                  <p className="text-2xl font-bold text-[var(--fg)]">~{(result.total_hours / 8).toFixed(1)}</p>
                  <p className="text-xs text-[var(--fg-muted)]">person-days</p>
                </div>
                <div>
                  <p className="text-2xl font-bold text-[var(--fg)]">~{(result.total_hours / 40).toFixed(1)}</p>
                  <p className="text-xs text-[var(--fg-muted)]">person-weeks</p>
                </div>
              </div>
              <p className="text-[11px] text-[var(--fg-muted)]">
                Model-based estimate from configurable per-tier anchors, not a quote. Conversion effort varies with team
                skills and data specifics.
              </p>
            </Card>
          )}

          {/* Top complex workflows */}
          <Card className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <Braces className="h-4 w-4 text-[var(--ring)]" />
              <h2 className="text-sm font-semibold text-[var(--fg)]">Most Complex Workflows</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--fg-muted)]">
                    <th className="pb-2 font-medium">Workflow</th>
                    <th className="pb-2 font-medium">Difficulty</th>
                    <th className="pb-2 text-right font-medium">Score</th>
                    <th className="pb-2 text-right font-medium">Tools</th>
                    <th className="pb-2 text-right font-medium">Depth</th>
                    <th className="pb-2 text-right font-medium">Coverage</th>
                    {result.total_hours != null && <th className="pb-2 text-right font-medium">Hours</th>}
                  </tr>
                </thead>
                <tbody>
                  {result.workflows.slice(0, 10).map((w) => (
                    <tr key={w.file_name} className="border-b border-[var(--border)] last:border-0">
                      <td className="py-2 pr-3 text-[var(--fg)]">{w.file_name}</td>
                      <td className="py-2 pr-3">
                        <span className="inline-flex items-center gap-1.5">
                          <span
                            className="h-2 w-2 rounded-full"
                            style={{ backgroundColor: tierColor(w.complexity_level) }}
                          />
                          <span className="text-[var(--fg)]">{w.complexity_level}</span>
                        </span>
                      </td>
                      <td className="py-2 text-right tabular-nums text-[var(--fg)]">{w.complexity_score.toFixed(1)}</td>
                      <td className="py-2 text-right tabular-nums text-[var(--fg)]">{w.node_count}</td>
                      <td className="py-2 text-right tabular-nums text-[var(--fg)]">{w.max_dag_depth}</td>
                      <td className="py-2 text-right tabular-nums text-[var(--fg)]">{w.coverage_percentage.toFixed(0)}%</td>
                      {result.total_hours != null && (
                        <td className="py-2 text-right tabular-nums text-[var(--fg-muted)]">
                          {w.estimated_hours == null ? "—" : `~${w.estimated_hours.toFixed(0)}`}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </motion.div>
      )}
    </div>
  );
}
