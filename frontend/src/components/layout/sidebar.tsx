import { Link, useRouterState } from "@tanstack/react-router";
import { Home, Grid3X3, Info, Moon, Sun, Menu, X, Settings, Check, ArrowLeftRight } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { useThemeStore } from "@/stores/theme";
import { Button } from "@/components/ui/button";
import { useProjectContext, type ProjectWorkflowView } from "@/hooks/use-project-context";
import { isAtOrPast } from "@/stores/local-project";
import { STEPS, stepPath, type StepDef } from "@/lib/steps";

declare const __BUILD_SHA__: string;
declare const __BUILD_DATE__: string;

const REFERENCE = [
  { to: "/reference/tools", label: "Tool coverage", icon: Grid3X3 },
  { to: "/settings", label: "Settings", icon: Settings },
  { to: "/about", label: "About", icon: Info },
];

/** "n/total" for a step that tracks a stage; the file count for Workflows. */
function stepProgress(step: StepDef, workflows: ProjectWorkflowView[]): { text: string; done: boolean } | null {
  const total = workflows.length;
  if (step.slug === "workflows") return { text: String(total), done: false };
  if (!step.stage || total === 0) return null;
  const n = workflows.filter((w) => isAtOrPast(w.stage, step.stage!)).length;
  return { text: `${n}/${total}`, done: n === total };
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-3 pt-5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--fg-muted)]">
      {children}
    </div>
  );
}

export function Sidebar() {
  const theme = useThemeStore((s) => s.theme);
  const toggle = useThemeStore((s) => s.toggle);
  const [open, setOpen] = useState(false);
  const currentPath = useRouterState().location.pathname;
  const ctx = useProjectContext();
  const inProject = ctx.projectId != null;

  const linkClass = (active: boolean, disabled = false) =>
    cn(
      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
      disabled
        ? "cursor-default text-[var(--fg-muted)]/50"
        : active
          ? "bg-[var(--ring)]/10 text-[var(--ring)]"
          : "text-[var(--fg-muted)] hover:bg-[var(--border)]/50 hover:text-[var(--fg)]",
    );

  return (
    <>
      {/* Mobile hamburger */}
      <button
        aria-label="Toggle navigation"
        aria-expanded={open}
        className="fixed top-4 left-4 z-50 lg:hidden rounded-lg p-2 bg-[var(--bg-card)] border border-[var(--border)] shadow-sm"
        onClick={() => setOpen(!open)}
      >
        {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {open && <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setOpen(false)} />}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-60 flex-col bg-[var(--bg-sidebar)] border-r border-[var(--border)] transition-transform duration-200",
          "lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-6 py-5 border-b border-[var(--border)]">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--ring)] text-white font-bold text-sm">
            a2d
          </div>
          <div>
            <div className="text-sm font-semibold text-[var(--fg)]">Alteryx to Databricks</div>
            <div className="text-xs text-[var(--fg-muted)]">Migration Accelerator</div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 overflow-y-auto" aria-label="Main">
          <Link to="/" onClick={() => setOpen(false)} className={linkClass(currentPath === "/")}>
            <Home className="h-4 w-4" />
            Projects
          </Link>

          {/* The open project and its steps, in order. */}
          {inProject ? (
            <>
              <SectionLabel>Current project</SectionLabel>
              <div className="px-3 pb-2">
                <div className="truncate text-sm font-semibold text-[var(--fg)]" title={ctx.name}>
                  {ctx.name || "…"}
                </div>
                <div className="mt-0.5 flex items-center justify-between text-xs text-[var(--fg-muted)]">
                  <span>
                    {ctx.saved ? "Saved" : "This session only"} · {ctx.workflows.length} workflow
                    {ctx.workflows.length === 1 ? "" : "s"}
                  </span>
                  <Link
                    to="/"
                    onClick={() => setOpen(false)}
                    className="inline-flex items-center gap-1 text-[var(--ring)] hover:underline"
                    title="Open a different project"
                  >
                    <ArrowLeftRight className="h-3 w-3" />
                    Switch
                  </Link>
                </div>
              </div>
              <ol className="space-y-0.5">
                {STEPS.map((step, i) => {
                  const to = stepPath(ctx.projectId!, step.slug);
                  const active = currentPath === to;
                  const progress = stepProgress(step, ctx.workflows);
                  return (
                    <li key={step.slug}>
                      <Link to={to} onClick={() => setOpen(false)} className={linkClass(active)}>
                        <span
                          className={cn(
                            "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] tabular-nums",
                            progress?.done
                              ? "border-success bg-success text-white"
                              : active
                                ? "border-[var(--ring)] text-[var(--ring)]"
                                : "border-[var(--border)]",
                          )}
                        >
                          {progress?.done ? <Check className="h-3 w-3" /> : i + 1}
                        </span>
                        <span className="flex-1 truncate">{step.label}</span>
                        {step.optional ? (
                          <span className="text-[10px] font-normal text-[var(--fg-muted)]">optional</span>
                        ) : (
                          progress && (
                            <span className="text-xs font-normal tabular-nums text-[var(--fg-muted)]">
                              {progress.text}
                            </span>
                          )
                        )}
                      </Link>
                    </li>
                  );
                })}
              </ol>
            </>
          ) : (
            <>
              <SectionLabel>Migration steps</SectionLabel>
              <ol className="space-y-0.5" aria-disabled="true">
                {STEPS.map((step, i) => (
                  <li key={step.slug} className={linkClass(false, true)}>
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-[var(--border)] text-[10px]">
                      {i + 1}
                    </span>
                    <span className="flex-1">{step.label}</span>
                  </li>
                ))}
              </ol>
              <p className="px-3 pt-2 text-xs text-[var(--fg-muted)]">
                Open or create a project to start.
              </p>
            </>
          )}

          <SectionLabel>Reference</SectionLabel>
          {REFERENCE.map(({ to, label, icon: Icon }) => (
            <Link key={to} to={to} onClick={() => setOpen(false)} className={linkClass(currentPath === to)}>
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          ))}
        </nav>

        {/* Theme toggle */}
        <div className="border-t border-[var(--border)] p-3">
          <Button variant="ghost" size="sm" onClick={toggle} className="w-full justify-start gap-3">
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </Button>
        </div>

        {/* Build version */}
        <div
          className="border-t border-[var(--border)] px-4 py-2 text-[10px] font-mono text-[var(--fg-muted)]"
          title={__BUILD_DATE__ ? `Built ${__BUILD_DATE__}` : undefined}
        >
          <a
            href={`https://github.com/databricks-solutions/alteryx-to-databricks-converter/commit/${__BUILD_SHA__}`}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-[var(--fg)]"
          >
            build {__BUILD_SHA__}
          </a>
        </div>
      </aside>
    </>
  );
}
