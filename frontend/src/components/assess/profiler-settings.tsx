import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { ChevronDown, SlidersHorizontal, RotateCcw } from "lucide-react";
import { Card } from "@/components/ui/card";
import { tierColor } from "./tier-meta";
import type { AssessDefaults } from "@/lib/api";

// Human-friendly labels for the Alteryx tool categories.
const CATEGORY_LABELS: Record<string, string> = {
  io: "Input / Output",
  container: "Containers",
  preparation: "Preparation",
  parse: "Parse",
  join: "Join",
  transform: "Transform",
  interface: "Interface / App",
  reporting: "Reporting",
  connectors: "Connectors",
  spatial: "Spatial",
  predictive: "Predictive / ML",
  developer: "Developer / Code",
  workflow: "Workflow control",
};

function labelFor(category: string): string {
  return CATEGORY_LABELS[category] ?? category.charAt(0).toUpperCase() + category.slice(1);
}

interface ProfilerSettingsProps {
  defaults: AssessDefaults;
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}

/**
 * On-screen editor for the profiler's per-category difficulty tiers. Defaults are
 * fetched from the server so the panel always matches the engine; a tool with no
 * converter is still forced to Very High regardless of these settings.
 */
export function ProfilerSettings({ defaults, value, onChange }: ProfilerSettingsProps) {
  const [open, setOpen] = useState(false);
  const categories = Object.keys(defaults.category_tiers);
  const modified = categories.filter((c) => value[c] !== defaults.category_tiers[c]).length;

  return (
    <Card className="p-0 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2 text-sm font-medium text-[var(--fg)]">
          <SlidersHorizontal className="h-4 w-4 text-[var(--fg-muted)]" />
          Difficulty settings
          <span className="text-xs font-normal text-[var(--fg-muted)]">
            {modified > 0 ? `${modified} customized` : "defaults"}
          </span>
        </span>
        <ChevronDown
          className={`h-4 w-4 text-[var(--fg-muted)] transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="border-t border-[var(--border)] px-4 py-4">
              <div className="mb-3 flex items-center justify-between">
                <p className="text-xs text-[var(--fg-muted)]">
                  Set the difficulty tier per tool category. Tools with no converter are always Very High.
                </p>
                {modified > 0 && (
                  <button
                    type="button"
                    onClick={() => onChange({ ...defaults.category_tiers })}
                    className="flex shrink-0 items-center gap-1 text-xs text-[var(--ring)] hover:underline"
                  >
                    <RotateCcw className="h-3 w-3" />
                    Reset
                  </button>
                )}
              </div>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {categories.map((cat) => {
                  const current = value[cat] ?? defaults.category_tiers[cat];
                  const isChanged = current !== defaults.category_tiers[cat];
                  return (
                    <label
                      key={cat}
                      className="flex items-center justify-between gap-2 rounded-lg border border-[var(--border)] px-3 py-2"
                    >
                      <span className="flex items-center gap-2 text-sm text-[var(--fg)]">
                        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: tierColor(current) }} />
                        {labelFor(cat)}
                        {isChanged && <span className="text-[10px] text-[var(--ring)]">•</span>}
                      </span>
                      <select
                        value={current}
                        onChange={(e) => onChange({ ...value, [cat]: e.target.value })}
                        className="rounded-md border border-[var(--border)] bg-[var(--bg-card)] px-2 py-1 text-xs text-[var(--fg)]"
                      >
                        {defaults.tiers.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                    </label>
                  );
                })}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}
