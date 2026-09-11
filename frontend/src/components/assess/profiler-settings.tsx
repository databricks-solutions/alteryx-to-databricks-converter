import { useMemo, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { ChevronDown, SlidersHorizontal, RotateCcw, Plus, X } from "lucide-react";
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
  /** Optional per-tool overrides (advanced). Keyed by tool name -> tier. */
  toolOverrides: Record<string, string>;
  onToolOverridesChange: (next: Record<string, string>) => void;
}

/**
 * On-screen editor for the profiler's per-category difficulty tiers. Defaults are
 * fetched from the server so the panel always matches the engine; a tool with no
 * converter is still forced to Very High regardless of these settings.
 */
export function ProfilerSettings({
  defaults,
  value,
  onChange,
  toolOverrides,
  onToolOverridesChange,
}: ProfilerSettingsProps) {
  const [open, setOpen] = useState(false);
  const [advOpen, setAdvOpen] = useState(false);
  const [pickTool, setPickTool] = useState("");
  const categories = Object.keys(defaults.category_tiers);
  const modified = categories.filter((c) => value[c] !== defaults.category_tiers[c]).length;

  // Tools grouped by category for the per-tool picker's <optgroup>s.
  const toolsByCategory = useMemo(() => {
    const groups: Record<string, typeof defaults.tools> = {};
    for (const t of defaults.tools) (groups[t.category] ??= []).push(t);
    return groups;
  }, [defaults.tools]);
  const toolDefault = (name: string) => defaults.tools.find((t) => t.name === name)?.default ?? "Medium";

  const addOverride = () => {
    if (!pickTool) return;
    onToolOverridesChange({ ...toolOverrides, [pickTool]: toolOverrides[pickTool] ?? toolDefault(pickTool) });
    setPickTool("");
  };
  const setOverrideTier = (tool: string, tier: string) =>
    onToolOverridesChange({ ...toolOverrides, [tool]: tier });
  const removeOverride = (tool: string) => {
    const next = { ...toolOverrides };
    delete next[tool];
    onToolOverridesChange(next);
  };
  const overrideCount = Object.keys(toolOverrides).length;

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
            {modified + overrideCount > 0 ? `${modified + overrideCount} customized` : "defaults"}
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
                        aria-label={`Difficulty tier for ${labelFor(cat)}`}
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

              {/* Advanced: optional per-tool overrides */}
              <div className="mt-4 border-t border-[var(--border)] pt-3">
                <button
                  type="button"
                  onClick={() => setAdvOpen((o) => !o)}
                  className="flex items-center gap-1.5 text-xs font-medium text-[var(--fg-muted)] hover:text-[var(--fg)]"
                  aria-expanded={advOpen}
                >
                  <ChevronDown className={`h-3.5 w-3.5 transition-transform ${advOpen ? "rotate-180" : ""}`} />
                  Advanced: per-tool overrides
                  {overrideCount > 0 && <span className="text-[var(--ring)]">({overrideCount})</span>}
                </button>

                {advOpen && (
                  <div className="mt-3 flex flex-col gap-3">
                    <p className="text-xs text-[var(--fg-muted)]">
                      Override the tier for a specific tool. Overrides win over the category default above.
                    </p>

                    {/* Active overrides */}
                    {overrideCount > 0 && (
                      <div className="flex flex-col gap-2">
                        {Object.entries(toolOverrides).map(([tool, tier]) => (
                          <div
                            key={tool}
                            className="flex items-center justify-between gap-2 rounded-lg border border-[var(--border)] px-3 py-2"
                          >
                            <span className="flex items-center gap-2 text-sm text-[var(--fg)]">
                              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: tierColor(tier) }} />
                              {tool}
                              <span className="text-[11px] text-[var(--fg-muted)]">
                                (default {toolDefault(tool)})
                              </span>
                            </span>
                            <span className="flex items-center gap-1.5">
                              <select
                                value={tier}
                                aria-label={`Difficulty tier for ${tool}`}
                                onChange={(e) => setOverrideTier(tool, e.target.value)}
                                className="rounded-md border border-[var(--border)] bg-[var(--bg-card)] px-2 py-1 text-xs text-[var(--fg)]"
                              >
                                {defaults.tiers.map((t) => (
                                  <option key={t} value={t}>
                                    {t}
                                  </option>
                                ))}
                              </select>
                              <button
                                type="button"
                                onClick={() => removeOverride(tool)}
                                aria-label={`Remove override for ${tool}`}
                                className="rounded p-1 text-[var(--fg-muted)] hover:text-[var(--fg)]"
                              >
                                <X className="h-3.5 w-3.5" />
                              </button>
                            </span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Add override */}
                    <div className="flex items-center gap-2">
                      <select
                        value={pickTool}
                        aria-label="Add a tool override"
                        onChange={(e) => setPickTool(e.target.value)}
                        className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--bg-card)] px-2 py-1.5 text-xs text-[var(--fg)]"
                      >
                        <option value="">Add a tool override…</option>
                        {Object.keys(toolsByCategory)
                          .sort()
                          .map((cat) => (
                            <optgroup key={cat} label={labelFor(cat)}>
                              {toolsByCategory[cat].map((t) => (
                                <option key={t.name} value={t.name}>
                                  {t.name} — {toolOverrides[t.name] ?? t.default}
                                </option>
                              ))}
                            </optgroup>
                          ))}
                      </select>
                      <button
                        type="button"
                        onClick={addOverride}
                        disabled={!pickTool}
                        className="flex shrink-0 items-center gap-1 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-xs text-[var(--fg)] hover:border-[var(--fg-muted)] disabled:opacity-40"
                      >
                        <Plus className="h-3.5 w-3.5" />
                        Add
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}
