import { motion } from "motion/react";
import { Card } from "@/components/ui/card";
import { TIER_META, TIER_ORDER, type Tier } from "./tier-meta";

interface ToolDifficultyProps {
  counts: Record<string, number>;
  types: Record<string, string[]>;
}

/**
 * The headline profiler visual: every tool instance across the estate placed on
 * a Low -> Very High difficulty ramp. A stacked bar shows the mix at a glance,
 * and per-tier cards give the count, share, and example tool types.
 */
export function ToolDifficulty({ counts, types }: ToolDifficultyProps) {
  const total = TIER_ORDER.reduce((sum, t) => sum + (counts[t] ?? 0), 0);
  const pct = (n: number) => (total ? (n / total) * 100 : 0);

  return (
    <Card className="flex flex-col gap-5">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[var(--fg)]">Tool Difficulty Breakdown</h2>
          <p className="text-xs text-[var(--fg-muted)] mt-0.5">
            {total.toLocaleString()} tool{total === 1 ? "" : "s"} across the estate, by conversion difficulty
          </p>
        </div>
      </div>

      {/* Stacked ramp */}
      <div
        className="flex h-3 w-full overflow-hidden rounded-full bg-[var(--bg-subtle,var(--border))]"
        role="img"
        aria-label={`Tool difficulty distribution: ${TIER_ORDER.map(
          (t) => `${t} ${counts[t] ?? 0} (${pct(counts[t] ?? 0).toFixed(0)}%)`,
        ).join(", ")}`}
      >
        {TIER_ORDER.map((tier) => {
          const width = pct(counts[tier] ?? 0);
          if (width === 0) return null;
          return (
            <motion.div
              key={tier}
              initial={{ width: 0 }}
              animate={{ width: `${width}%` }}
              transition={{ duration: 0.5, ease: "easeOut" }}
              style={{ backgroundColor: TIER_META[tier].color }}
              title={`${tier}: ${counts[tier] ?? 0} (${width.toFixed(0)}%)`}
            />
          );
        })}
      </div>

      {/* Per-tier cards */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {TIER_ORDER.map((tier, i) => {
          const count = counts[tier] ?? 0;
          const examples = types[tier] ?? [];
          return (
            <motion.div
              key={tier}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: i * 0.04 }}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-3"
            >
              <div className="flex items-center gap-2">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: TIER_META[tier].color }}
                />
                <span className="text-xs font-medium text-[var(--fg)]">{tier}</span>
              </div>
              <div className="mt-2 flex items-baseline gap-1.5">
                <span className="text-2xl font-bold text-[var(--fg)]">{count}</span>
                <span className="text-xs text-[var(--fg-muted)]">{pct(count).toFixed(0)}%</span>
              </div>
              <p className="mt-0.5 text-[11px] text-[var(--fg-muted)]">{TIER_META[tier].blurb}</p>
              {examples.length > 0 && (
                <p className="mt-2 text-[11px] leading-snug text-[var(--fg-muted)] line-clamp-3">
                  {examples.slice(0, 8).join(", ")}
                  {examples.length > 8 ? "…" : ""}
                </p>
              )}
            </motion.div>
          );
        })}
      </div>
    </Card>
  );
}

/** Compact horizontal-bar chart of workflow counts per complexity level. */
export function DifficultyDistribution({ distribution }: { distribution: Record<string, number> }) {
  const max = Math.max(1, ...TIER_ORDER.map((t) => distribution[t] ?? 0));
  const total = TIER_ORDER.reduce((s, t) => s + (distribution[t] ?? 0), 0);
  return (
    <Card className="flex flex-col gap-4">
      <div>
        <h2 className="text-sm font-semibold text-[var(--fg)]">Migration Difficulty</h2>
        <p className="text-xs text-[var(--fg-muted)] mt-0.5">Workflows by overall complexity</p>
      </div>
      <div className="flex flex-col gap-2.5">
        {TIER_ORDER.map((tier) => {
          const count = distribution[tier] ?? 0;
          return (
            <div key={tier} className="flex items-center gap-3">
              <span className="w-20 shrink-0 text-xs text-[var(--fg-muted)]">{tier}</span>
              <div className="h-5 flex-1 overflow-hidden rounded bg-[var(--bg-subtle,var(--border))]">
                <motion.div
                  className="h-full rounded"
                  style={{ backgroundColor: TIER_META[tier as Tier].color }}
                  initial={{ width: 0 }}
                  animate={{ width: `${(count / max) * 100}%` }}
                  transition={{ duration: 0.5, ease: "easeOut" }}
                />
              </div>
              <span className="w-14 shrink-0 text-right text-xs tabular-nums text-[var(--fg)]">
                {count} <span className="text-[var(--fg-muted)]">({total ? Math.round((count / total) * 100) : 0}%)</span>
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
