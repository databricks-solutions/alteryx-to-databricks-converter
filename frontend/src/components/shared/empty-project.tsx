/** What a step shows when its project has no workflows yet. */
export function EmptyProject() {
  return (
    <p className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6 text-sm text-[var(--fg-muted)]">
      This project has no workflows yet. Add its Alteryx files on the Workflows step (step 1 in the sidebar).
    </p>
  );
}
