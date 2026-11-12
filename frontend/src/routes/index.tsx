import { useState } from "react";
import { motion } from "motion/react";
import { Link, useNavigate } from "@tanstack/react-router";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { MetricCard } from "@/components/shared/metric-card";
import { FileDropzone } from "@/components/shared/file-dropzone";
import { useStats } from "@/hooks/use-tools";
import { useProjects, useCreateProject, isProjectsUnavailable } from "@/hooks/use-project";
import { useProjectStore } from "@/stores/project";
import { LOCAL_PROJECT_ID, useLocalProjectStore, isAtOrPast } from "@/stores/local-project";
import { STEPS, stepPath } from "@/lib/steps";
import type { ProjectSummary, WorkflowStage } from "@/lib/api";
import { Boxes, Code, Database, Zap, FolderPlus, Loader2, X, ArrowRight, Info } from "lucide-react";

const STAGE_ORDER: WorkflowStage[] = ["uploaded", "assessed", "converted", "reviewed", "deployed"];

/** How far a project is: workflows converted and reviewed, out of the total. */
function ProjectProgress({ project }: { project: ProjectSummary }) {
  const counts = project.rollups?.stage_counts;
  const total = project.rollups?.total_workflows ?? 0;
  if (!counts || total === 0) return null;
  const atOrPast = (target: WorkflowStage) =>
    STAGE_ORDER.filter((s) => isAtOrPast(s, target)).reduce((n, s) => n + (counts[s] ?? 0), 0);
  return (
    <span className="text-xs text-[var(--fg-muted)] tabular-nums">
      {atOrPast("assessed")}/{total} assessed · {atOrPast("converted")}/{total} converted ·{" "}
      {atOrPast("reviewed")}/{total} reviewed
    </span>
  );
}

export function HomePage() {
  const { data: stats, isLoading, error } = useStats();
  const projects = useProjects();
  const create = useCreateProject();
  const createLocal = useLocalProjectStore((s) => s.create);
  const localName = useLocalProjectStore((s) => s.name);
  const localCount = useLocalProjectStore((s) => s.workflows.length);
  const lastProjectId = useProjectStore((s) => s.lastProjectId);
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);

  // No database on this server: projects can still be used, just not saved.
  const unavailable = isProjectsUnavailable(projects.error);
  const list = projects.data?.projects ?? [];
  const resume = list.find((p) => p.id === lastProjectId);

  const handleCreate = () => {
    if (files.length === 0) return;
    const projectName = name.trim() || "Untitled migration";
    if (unavailable) {
      if (localName && !window.confirm(`This replaces the session project "${localName}". Continue?`)) return;
      createLocal(projectName, files);
      navigate({ to: stepPath(LOCAL_PROJECT_ID, "workflows") });
      return;
    }
    create.mutate(
      { name: projectName, files },
      { onSuccess: (project) => navigate({ to: stepPath(project.id, "workflows") }) },
    );
  };

  return (
    <div className="space-y-10">
      {/* Hero */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[var(--ring)] to-blue-700 p-10 text-white"
      >
        <div className="relative z-10">
          <h1 className="text-4xl font-bold mb-3">Alteryx to Databricks</h1>
          <p className="text-lg text-white/80 max-w-xl">
            Enterprise-grade migration accelerator. Upload your Alteryx workflows once, then assess them, build the
            business case, convert them to Databricks, and review the results — all in one project.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <button
              onClick={() => setCreating(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-white text-blue-700 hover:bg-white/90 px-4 py-2 text-sm font-medium transition-colors"
            >
              <FolderPlus className="h-4 w-4" />
              Start a new migration
            </button>
            {resume && (
              <Link
                to={stepPath(resume.id, "workflows")}
                className="inline-flex items-center gap-2 rounded-lg bg-white/20 hover:bg-white/30 px-4 py-2 text-sm font-medium transition-colors"
              >
                Resume {resume.name}
                <ArrowRight className="h-4 w-4" />
              </Link>
            )}
          </div>
        </div>
        <div className="absolute -top-20 -right-20 h-64 w-64 rounded-full bg-white/5" />
        <div className="absolute -bottom-10 -right-10 h-40 w-40 rounded-full bg-white/5" />
      </motion.div>

      {/* New migration: the drop zone only appears when you ask for it. */}
      {creating && (
        <Card className="flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <FolderPlus className="h-4 w-4 text-[var(--ring)]" />
            <h2 className="text-sm font-semibold text-[var(--fg)]">New migration</h2>
            <button
              aria-label="Cancel"
              onClick={() => {
                setCreating(false);
                setFiles([]);
              }}
              className="ml-auto rounded p-1 text-[var(--fg-muted)] hover:text-[var(--fg)]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <p className="text-xs text-[var(--fg-muted)]">
            Name the migration and add its Alteryx files. You can add, replace, or remove files later on the
            project's Workflows step. Every other step reads these files, so you won't upload anything again.
          </p>
          {unavailable && (
            <p className="flex items-start gap-2 text-xs text-[var(--fg-muted)]">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
              This server has no database, so this project will live in this browser tab only (a reload clears it).
            </p>
          )}
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Project name (e.g. Finance estate migration)"
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--fg)]"
          />
          <FileDropzone files={files} onFilesChange={setFiles} multiple />
          <div className="flex items-center gap-3">
            <Button onClick={handleCreate} disabled={files.length === 0 || create.isPending}>
              {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderPlus className="h-4 w-4" />}
              Create project
            </Button>
            {create.isError && <span className="text-xs text-destructive">{create.error.message}</span>}
          </div>
        </Card>
      )}

      {/* Projects */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[var(--fg-muted)]">Your migrations</h2>
          {!creating && list.length > 0 && (
            <Button size="sm" variant="secondary" onClick={() => setCreating(true)}>
              <FolderPlus className="h-4 w-4" />
              New migration
            </Button>
          )}
        </div>
        {localName && (
          <Link
            to={stepPath(LOCAL_PROJECT_ID, "workflows")}
            className="mb-3 flex items-center gap-4 rounded-xl border border-warning/30 bg-[var(--bg-card)] px-4 py-3 hover:bg-[var(--bg-sidebar)]"
          >
            <Boxes className="h-4 w-4 shrink-0 text-warning" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-[var(--fg)]">{localName}</div>
              <div className="mt-0.5 text-xs text-[var(--fg-muted)]">
                {localCount} workflow{localCount === 1 ? "" : "s"} · this browser session only
              </div>
            </div>
            <ArrowRight className="h-4 w-4 text-[var(--fg-muted)]" />
          </Link>
        )}
        {projects.isLoading ? (
          <Skeleton className="h-24 rounded-xl" />
        ) : list.length > 0 ? (
          <div className="rounded-xl border border-[var(--border)] overflow-hidden">
            {list.map((p) => (
              <Link
                key={p.id}
                to={stepPath(p.id, "workflows")}
                className="flex items-center gap-4 border-b border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 last:border-b-0 hover:bg-[var(--bg-sidebar)]"
              >
                <Boxes className="h-4 w-4 shrink-0 text-[var(--ring)]" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-[var(--fg)]">{p.name}</div>
                  <div className="mt-0.5 flex flex-wrap gap-x-3">
                    <span className="text-xs text-[var(--fg-muted)]">
                      {p.rollups?.total_workflows ?? 0} workflow{(p.rollups?.total_workflows ?? 0) === 1 ? "" : "s"}
                    </span>
                    <ProjectProgress project={p} />
                  </div>
                </div>
                <span className="text-xs text-[var(--fg-muted)]">
                  {p.updated_at
                    ? new Date(p.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })
                    : ""}
                </span>
                <ArrowRight className="h-4 w-4 text-[var(--fg-muted)]" />
              </Link>
            ))}
          </div>
        ) : (
          !creating &&
          !localName && (
            <Card className="border-[var(--ring)]/20 bg-[var(--ring)]/5 p-4">
              <p className="text-sm font-medium text-[var(--fg)]">No migrations yet</p>
              <p className="mt-1 text-xs text-[var(--fg-muted)]">
                A project holds one migration: its Alteryx files and where each one is in the process.{" "}
                <button onClick={() => setCreating(true)} className="text-[var(--ring)] hover:underline">
                  Start one
                </button>{" "}
                to begin.
              </p>
            </Card>
          )
        )}
        {projects.isError && !unavailable && (
          <p className="mt-2 text-xs text-destructive">Couldn't load projects: {projects.error.message}</p>
        )}
      </div>

      {/* How a project moves — a description, not more navigation. */}
      <div>
        <h2 className="text-sm font-semibold text-[var(--fg-muted)] mb-3">How a migration works here</h2>
        <ol className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.slug} className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
              <div className="mb-1 flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--ring)]/10 text-[10px] font-semibold text-[var(--ring)]">
                  {i + 1}
                </span>
                <span className="text-sm font-semibold text-[var(--fg)]">{s.label}</span>
                {s.optional && <span className="text-[10px] text-[var(--fg-muted)]">optional</span>}
              </div>
              <p className="text-xs text-[var(--fg-muted)]">{s.blurb}</p>
            </li>
          ))}
        </ol>
      </div>

      {/* Engine stats */}
      {error ? (
        <div className="rounded-xl border border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/30 px-4 py-3">
          <p className="text-sm text-red-700 dark:text-red-400">
            Failed to connect to the API server. Start it with{" "}
            <code className="mx-1 rounded bg-red-100 dark:bg-red-900/40 px-1.5 py-0.5 text-xs">make serve</code> or{" "}
            <code className="rounded bg-red-100 dark:bg-red-900/40 px-1.5 py-0.5 text-xs">uvicorn server.main:app</code>.
          </p>
        </div>
      ) : isLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      ) : stats ? (
        <div>
          <h2 className="text-sm font-semibold text-[var(--fg-muted)] mb-3">Engine Capabilities</h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              label="Tool Coverage"
              value={Math.round((stats.supported_tools / stats.total_tools) * 100)}
              suffix="%"
              icon={<Boxes className="h-5 w-5" />}
            />
            <MetricCard label="Recognized Tools" value={stats.total_tools} icon={<Database className="h-5 w-5" />} />
            <MetricCard label="Expression Functions" value={stats.expression_functions} icon={<Code className="h-5 w-5" />} />
            <MetricCard label="Output Formats" value={stats.output_formats} icon={<Zap className="h-5 w-5" />} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
