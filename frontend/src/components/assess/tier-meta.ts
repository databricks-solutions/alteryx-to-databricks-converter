// Shared metadata for the migration difficulty tiers. The palette is an ordinal
// ramp (calm green -> alarm red) so severity reads at a glance in either theme.
// These labels match the backend (a2d.analyzer.profiler) and the CLI output.

export const TIER_ORDER = ["Low", "Medium", "High", "Very High"] as const;
export type Tier = (typeof TIER_ORDER)[number];

export const TIER_META: Record<Tier, { color: string; blurb: string }> = {
  Low: { color: "#10b981", blurb: "1:1 mapping" },
  Medium: { color: "#f59e0b", blurb: "Some rework" },
  High: { color: "#f97316", blurb: "Manual / special runtime" },
  "Very High": { color: "#ef4444", blurb: "Rebuild / no converter" },
};

export function tierColor(tier: string): string {
  return TIER_META[tier as Tier]?.color ?? "var(--fg-muted)";
}
