import type { ProjectWorkflowView } from "@/hooks/use-project-context";
import { isAtOrPast } from "@/lib/stages";

/**
 * Pick one of the project's converted workflows: what the Review and AI
 * completion steps use instead of an upload. Both work on a workflow after
 * Convert, so workflows that haven't been converted aren't offered.
 */
export function WorkflowPicker({
  workflows,
  value,
  onChange,
  label = "Workflow",
}: {
  workflows: ProjectWorkflowView[];
  value: string | null;
  onChange: (id: string) => void;
  label?: string;
}) {
  const converted = convertedWorkflows(workflows);
  return (
    <label className="flex flex-wrap items-center gap-3 text-sm">
      <span className="text-[var(--fg-muted)]">{label}</span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-0 max-w-full rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-1.5 text-sm text-[var(--fg)] sm:min-w-64"
      >
        {value == null && <option value="">Choose a workflow…</option>}
        {converted.map((w) => (
          <option key={w.id} value={w.id}>
            {w.file_name} ({w.stage})
          </option>
        ))}
      </select>
    </label>
  );
}

export function convertedWorkflows(workflows: ProjectWorkflowView[]): ProjectWorkflowView[] {
  return workflows.filter((w) => isAtOrPast(w.stage, "converted"));
}

/** The workflow a step should start on: the first converted one not yet past
 * ``notPast``, else the first converted one. */
export function defaultWorkflowId(
  workflows: ProjectWorkflowView[],
  notPast: ProjectWorkflowView["stage"],
): string | null {
  const converted = convertedWorkflows(workflows);
  return (converted.find((w) => !isAtOrPast(w.stage, notPast)) ?? converted[0])?.id ?? null;
}

/** What a step that needs a converted workflow shows when there isn't one. */
export function NoConvertedWorkflows({ what }: { what: string }) {
  return (
    <p className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6 text-sm text-[var(--fg-muted)]">
      No workflows are converted yet. {what} works on a converted workflow, so convert one on the Convert step (step
      4 in the sidebar) first.
    </p>
  );
}
