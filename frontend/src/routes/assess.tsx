import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { MetricCard } from "@/components/shared/metric-card";
import { ToolDifficulty, DifficultyDistribution } from "@/components/assess/tool-difficulty";
import { ProfilerSettings } from "@/components/assess/profiler-settings";
import { tierColor } from "@/components/assess/tier-meta";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAssessDefaults } from "@/hooks/use-assess";
import { useEstateView } from "@/hooks/use-estate-view";
import { api } from "@/lib/api";
import {
  Workflow,
  Boxes,
  Shapes,
  Database,
  Braces,
  Ruler,
  Loader2,
  Clock,
} from "lucide-react";

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-[var(--border)] py-2 last:border-0">
      <span className="text-xs text-[var(--fg-muted)]">{label}</span>
      <span className="text-sm font-medium tabular-nums text-[var(--fg)]">{value}</span>
    </div>
  );
}

/** Tool-by-difficulty profile of the open project. Runs by itself with the
 * default tiers; adjust the tiers (or turn on hour estimates) and re-run. */
export function AssessPage() {
  const [hours, setHours] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [categoryTiers, setCategoryTiers] = useState<Record<string, string>>({});
  const [toolOverrides, setToolOverrides] = useState<Record<string, string>>({});
  const { data: defaults } = useAssessDefaults();
  const view = useEstateView<"profile", { hours?: boolean; config?: Record<string, unknown> }>({
    kind: "profile",
    run: (source, args) => api.assess(source, args),
    auto: true,
    onResult: (data, ctx) => ctx.afterEstatePass({ analyzed: data.analyzed_files ?? [] }),
  });

  // Seed the tier editor once: from the settings the shown profile was run with
  // (so the inputs match the numbers), else from the server defaults.
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current || !defaults) return;
    seeded.current = true;
    const last = view.args?.config as
      | { category_tiers?: Record<string, string>; tool_overrides?: Record<string, string> }
      | undefined;
    setCategoryTiers({ ...defaults.category_tiers, ...(last?.category_tiers ?? {}) });
    setToolOverrides({ ...(last?.tool_overrides ?? {}) });
    setHours(Boolean(view.args?.hours));
  }, [defaults, view.args]);

  const result = view.data;

  const runProfile = () => {
    // Only send overrides that differ from the server defaults.
    const categoryChanged =
      defaults &&
      Object.keys(categoryTiers).some((c) => categoryTiers[c] !== defaults.category_tiers[c]);
    const config: Record<string, unknown> = {};
    if (categoryChanged) config.category_tiers = categoryTiers;
    if (Object.keys(toolOverrides).length > 0) config.tool_overrides = toolOverrides;
    view.rerun({ hours, config: Object.keys(config).length ? config : undefined });
    setShowSettings(false);
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Optional tuning — inputs, not uploads. */}
      <Card className="flex flex-col gap-4">
        <button
          className="flex items-center gap-2 text-left text-sm font-semibold text-[var(--fg)]"
          onClick={() => setShowSettings((v) => !v)}
          aria-expanded={showSettings}
        >
          <Ruler className="h-4 w-4 text-[var(--ring)]" />
          Adjust difficulty tiers and effort estimate
          <span className="ml-auto text-xs font-normal text-[var(--fg-muted)]">
            {showSettings ? "Hide" : "Optional"}
          </span>
        </button>
        {showSettings && (
          <>
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
                  Rule-based estimate from per-tier hour anchors. Treat any hours as indicative, not a quote.
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
            <div>
              <Button size="sm" onClick={runProfile} disabled={view.isPending}>
                <Ruler className="h-4 w-4" />
                Re-run with these settings
              </Button>
            </div>
          </>
        )}
      </Card>

      {view.error && !view.isPending && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <p className="font-medium">Profiling failed</p>
          <p className="mt-1 text-[var(--fg-muted)]">{view.error.message}</p>
          <Button variant="ghost" size="sm" className="mt-2" onClick={() => view.rerun()}>
            Try again
          </Button>
        </div>
      )}

      {/* Loading */}
      {view.isPending && (
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-2 text-sm text-[var(--fg-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            Profiling {view.ctx.workflows.length} workflow{view.ctx.workflows.length === 1 ? "" : "s"}…
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
      {result && !view.isPending && (
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
                Rule-based estimate from configurable per-tier hour anchors, not a quote. Conversion effort varies with team
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
