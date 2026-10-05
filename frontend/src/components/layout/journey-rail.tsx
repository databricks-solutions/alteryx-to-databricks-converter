import { Link } from "@tanstack/react-router";
import { useActiveProject } from "@/hooks/use-project";
import type { WorkflowStage } from "@/lib/api";

// The migration lifecycle, in order, with the stage each step counts.
const STEPS: { stage: WorkflowStage; label: string }[] = [
  { stage: "uploaded", label: "Uploaded" },
  { stage: "assessed", label: "Assessed" },
  { stage: "converted", label: "Converted" },
  { stage: "reviewed", label: "Reviewed" },
  { stage: "deployed", label: "Deployed" },
];

/**
 * A thin strip showing the active migration's progress by stage. Present on
 * every screen so the app reads as one journey, not a set of tools. Hidden when
 * no project is active (the app's default, no-backend behavior is unchanged).
 */
export function JourneyRail() {
  const { data: project } = useActiveProject();
  if (!project) return null;

  const counts = project.rollups?.stage_counts ?? {};
  const total = project.rollups?.total_workflows ?? project.workflows.length;

  return (
    <div className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--bg-card)]/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-1 px-6 py-2 text-xs">
        <Link to="/project" className="font-medium text-[var(--fg)] hover:text-[var(--ring)]">
          {project.name}
        </Link>
        <span className="text-[var(--fg-muted)]">{total} workflow{total === 1 ? "" : "s"}</span>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {STEPS.map((step, i) => {
            const n = (counts as Record<string, number>)[step.stage] ?? 0;
            return (
              <span key={step.stage} className="flex items-center gap-1.5">
                {i > 0 && <span className="text-[var(--fg-muted)]/50">→</span>}
                <span className={n > 0 ? "text-[var(--fg)]" : "text-[var(--fg-muted)]"}>
                  {step.label}
                  <span className="ml-1 tabular-nums text-[var(--fg-muted)]">{n}</span>
                </span>
              </span>
            );
          })}
        </div>
        {project.rollups?.mean_coverage_pct != null && (
          <span className="ml-auto text-[var(--fg-muted)]">
            {project.rollups.mean_coverage_pct}% avg coverage
          </span>
        )}
      </div>
    </div>
  );
}
