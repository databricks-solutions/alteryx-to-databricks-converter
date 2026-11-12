import type { ProjectWorkflowView } from "@/hooks/use-project-context";
import { isAtOrPast } from "@/stores/local-project";

/**
 * Pick one of the project's workflows — what single-workflow steps use
 * instead of an upload. Converted workflows are listed first.
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
  const converted = workflows.filter((w) => isAtOrPast(w.stage, "converted"));
  const others = workflows.filter((w) => !isAtOrPast(w.stage, "converted"));
  return (
    <label className="flex flex-wrap items-center gap-3 text-sm">
      <span className="text-[var(--fg-muted)]">{label}</span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-64 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-1.5 text-sm text-[var(--fg)]"
      >
        {value == null && <option value="">Choose a workflow…</option>}
        {converted.length > 0 && (
          <optgroup label="Converted">
            {converted.map((w) => (
              <option key={w.id} value={w.id}>
                {w.file_name} ({w.stage})
              </option>
            ))}
          </optgroup>
        )}
        {others.length > 0 && (
          <optgroup label="Not converted yet">
            {others.map((w) => (
              <option key={w.id} value={w.id}>
                {w.file_name} ({w.stage})
              </option>
            ))}
          </optgroup>
        )}
      </select>
    </label>
  );
}

/** The workflow a single-workflow step should start on: the first converted one
 * that isn't past `notPast` yet, else the first converted, else the first. */
export function defaultWorkflowId(
  workflows: ProjectWorkflowView[],
  notPast: ProjectWorkflowView["stage"],
): string | null {
  const converted = workflows.filter((w) => isAtOrPast(w.stage, "converted"));
  const pending = converted.find((w) => !isAtOrPast(w.stage, notPast));
  return (pending ?? converted[0] ?? workflows[0])?.id ?? null;
}
