import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { StepHeader } from "@/components/layout/step-header";
import { CodeBlock } from "@/components/shared/code-block";
import { EmptyProject } from "@/components/shared/empty-project";
import {
  NoConvertedWorkflows,
  WorkflowPicker,
  convertedWorkflows,
  defaultWorkflowId,
} from "@/components/shared/workflow-picker";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useProjectContext } from "@/hooks/use-project-context";
import { useConvertOptions } from "@/hooks/use-convert-options";
import { useToastStore } from "@/stores/toast";
import { api, type AICompletion, type CellCompletion, type MigrationContext } from "@/lib/api";
import { downloadText } from "@/lib/files";
import { Sparkles, Download, Loader2, FileText, AlertTriangle, CheckCircle2 } from "lucide-react";

const GAP_LABEL: Record<string, string> = {
  unsupported_tool: "Unsupported tool",
  todo: "TODO left in the code",
  review_warning: "Needs review",
  graph: "Workflow structure",
};

// AI-written code is the thing to check (amber); keeping the converter's code is
// the safe outcome (grey), not an error.
const CELL_BADGE: Record<CellCompletion["status"], { variant: "warning" | "secondary"; label: string }> = {
  completed: { variant: "warning", label: "AI-completed, review it" },
  failed: { variant: "secondary", label: "Kept as converted" },
  skipped: { variant: "secondary", label: "Skipped" },
};

/**
 * Step 6 (optional). The only place in the app that produces non-deterministic
 * output. For one converted workflow it shows what the converter couldn't
 * finish, and can have a model fill in just those steps, as a separate, clearly
 * marked copy of the PySpark notebook. The deterministic output from Convert is
 * never changed.
 */
export function AiCompletionPage() {
  const ctx = useProjectContext();
  const opts = useConvertOptions(ctx.projectId);
  const addToast = useToastStore((s) => s.add);
  const status = useQuery({ queryKey: ["ai-status"], queryFn: api.aiStatus, staleTime: 60_000 });
  const enabled = status.data?.enabled ?? false;
  const [workflowId, setWorkflowId] = useState<string | null>(() => defaultWorkflowId(ctx.workflows, "deployed"));

  useEffect(() => {
    if (workflowId == null && ctx.workflows.length > 0) setWorkflowId(defaultWorkflowId(ctx.workflows, "deployed"));
  }, [workflowId, ctx.workflows]);

  const source = workflowId ? ctx.workflowSource(workflowId) : null;

  // What needs work: deterministic, so it works without AI configured.
  const gaps = useQuery<MigrationContext>({
    queryKey: ["ai-gaps", ctx.projectId, workflowId, ctx.signature, opts.catalogName, opts.schemaName],
    queryFn: () => api.aiGaps(source!, opts),
    enabled: source != null,
    retry: false,
  });

  const complete = useMutation<AICompletion, Error>({ mutationFn: () => api.aiComplete(source!, opts) });
  const notes = useMutation<string, Error>({
    mutationFn: () => api.aiNotes(source!, opts),
    onSuccess: (markdown) => {
      downloadText(`${gaps.data?.workflow_name ?? "workflow"}_ai_suggestions.md`, markdown, "text/markdown;charset=utf-8");
      addToast("AI suggestions downloaded", "success");
    },
    onError: (e) => addToast(e.message, "error"),
  });

  // A new pick starts clean.
  const { reset: resetComplete } = complete;
  useEffect(() => {
    resetComplete();
  }, [workflowId, resetComplete]);

  const result = complete.data;
  const completable = gaps.data?.completable ?? [];

  return (
    <div>
      <StepHeader slug="ai-completion">
        {result && (
          <Button size="sm" onClick={() => downloadText(result.filename, result.content, "text/x-python;charset=utf-8")}>
            <Download className="h-4 w-4" />
            Download AI-completed notebook
          </Button>
        )}
      </StepHeader>

      <div className="space-y-6">
        {/* Say plainly what this is before anything else. */}
        <div className="flex items-start gap-3 rounded-xl border border-[var(--ring)]/30 bg-[var(--ring)]/5 px-4 py-3 text-sm">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-[var(--ring)]" />
          <div className="space-y-1 text-[var(--fg-muted)]">
            <p>
              <strong className="text-[var(--fg)]">This is the only step that uses AI, and it's optional.</strong>{" "}
              Everything from Convert is deterministic: the same workflow always produces the same code. Here a
              model proposes code for just the steps the converter couldn't finish (unsupported tools, TODOs), and
              you get it as a <strong className="text-[var(--fg)]">separate copy</strong> of the PySpark notebook
              with every AI-written step marked.
            </p>
            <p>
              Nothing here has been run or verified, and your converted files aren't changed. Review every marked
              step before you use it. PySpark notebooks only, for now.
            </p>
          </div>
        </div>

        {!status.isLoading && !enabled && (
          <div className="rounded-xl border border-warning/30 bg-warning/5 p-4 text-sm">
            <p className="font-medium text-[var(--fg)]">AI completion isn't turned on for this app</p>
            <p className="mt-1 text-[var(--fg-muted)]">
              Ask whoever runs the app to turn it on. You can still see below which steps it would fill in.
            </p>
            <details className="mt-2 text-xs text-[var(--fg-muted)]">
              <summary className="cursor-pointer">For the app's administrator</summary>
              Set{" "}
              <code className="rounded bg-[var(--bg-sidebar)] px-1 py-0.5 font-mono">A2D_FMAPI_ENDPOINT</code> to a
              Databricks Foundation Model API serving endpoint (and{" "}
              <code className="rounded bg-[var(--bg-sidebar)] px-1 py-0.5 font-mono">A2D_FMAPI_TOKEN</code> if it
              needs a token), then restart the app. In a Databricks Apps deployment, pass{" "}
              <code className="rounded bg-[var(--bg-sidebar)] px-1 py-0.5 font-mono">--var fmapi_endpoint=…</code> at
              deploy time.
            </details>
          </div>
        )}

        {ctx.workflows.length === 0 ? (
          <EmptyProject />
        ) : convertedWorkflows(ctx.workflows).length === 0 ? (
          <NoConvertedWorkflows what="AI completion" />
        ) : (
          <>
            <WorkflowPicker workflows={ctx.workflows} value={workflowId} onChange={setWorkflowId} />

            {gaps.isLoading && <Skeleton className="h-32 rounded-xl" />}
            {gaps.error && <p className="text-sm text-destructive">{gaps.error.message}</p>}
            {gaps.data && (
              <Card className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-sm font-semibold text-[var(--fg)]">What the converter couldn't finish</h2>
                  {gaps.data.coverage != null && (
                    <span className="text-xs text-[var(--fg-muted)]">
                      {gaps.data.coverage.toFixed(0)}% deterministic coverage
                    </span>
                  )}
                </div>
                {gaps.data.gaps.length === 0 ? (
                  <p className="flex items-center gap-2 text-sm text-[var(--fg-muted)]">
                    <CheckCircle2 className="h-4 w-4 text-success" />
                    The converter found nothing it couldn't finish, so there's nothing for a model to fill in.
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {gaps.data.gaps.map((g, i) => (
                      <li key={i} className="flex flex-wrap items-baseline gap-2 text-sm">
                        <Badge variant={g.kind === "unsupported_tool" ? "destructive" : "warning"}>
                          {GAP_LABEL[g.kind] ?? g.kind}
                        </Badge>
                        <span className="text-[var(--fg)]">{g.summary}</span>
                        {g.node_id != null && <span className="text-xs text-[var(--fg-muted)]">step {g.node_id}</span>}
                      </li>
                    ))}
                  </ul>
                )}
                {gaps.data.gaps.length > 0 && (
                  <p className="text-xs text-[var(--fg-muted)]">
                    {completable.length === 0
                      ? "None of these are steps AI completion fills in (it works on unsupported tools and TODO stubs). Review them on the Review step."
                      : `AI completion would fill in ${completable.length} step${completable.length === 1 ? "" : "s"}: ${completable
                          .map((c) => `step ${c.node_id}${c.tool_type ? ` (${c.tool_type})` : ""}`)
                          .join(", ")}. The rest are notes to review yourself.`}
                  </p>
                )}
              </Card>
            )}

            {/* The AI actions, together and labeled as AI. */}
            {enabled && gaps.data && completable.length > 0 && (
              <Card className="flex flex-col gap-3 border-[var(--ring)]/30">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-[var(--ring)]" />
                  <h2 className="text-sm font-semibold text-[var(--fg)]">Generate with AI (not deterministic)</h2>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button onClick={() => complete.mutate()} disabled={complete.isPending}>
                    {complete.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                    Generate AI-completed notebook
                  </Button>
                  <Button variant="secondary" onClick={() => notes.mutate()} disabled={notes.isPending}>
                    {notes.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                    Download AI suggestions (.md, unverified)
                  </Button>
                </div>
                {complete.isPending && (
                  <p className="text-xs text-[var(--fg-muted)]" role="status" aria-live="polite">
                    Asking the model for each step that needs work. This can take a minute or two for a large
                    workflow.
                  </p>
                )}
                {complete.error && <p className="text-sm text-destructive">{complete.error.message}</p>}
              </Card>
            )}

            {result && <CompletionResult result={result} />}
          </>
        )}
      </div>
    </div>
  );
}

function CompletionResult({ result }: { result: AICompletion }) {
  const { summary } = result;
  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-semibold text-[var(--fg)]">{result.filename}</span>
        <span className="text-xs text-[var(--fg-muted)]">
          {summary.completed} of {summary.cells_needing_work} step(s) completed by AI
          {summary.failed > 0 && ` · ${summary.failed} kept as converted (the AI code didn't pass the checks)`}
          {summary.skipped > 0 && ` · ${summary.skipped} skipped`}
        </span>
        <span className="ml-auto text-xs text-[var(--fg-muted)]">
          The converted notebook is still <code>{result.deterministic_filename}</code>, unchanged.
        </span>
      </Card>

      {result.cells.map((cell, i) => (
        <Card key={i} className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-[var(--fg)]">
              Step {cell.node_id ?? "?"}
              {cell.tool_type ? ` · ${cell.tool_type}` : ""}
            </span>
            <Badge variant={CELL_BADGE[cell.status].variant}>{CELL_BADGE[cell.status].label}</Badge>
          </div>
          {cell.reason && (
            <p className="flex items-start gap-1.5 text-xs text-[var(--fg-muted)]">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
              {cell.reason}
            </p>
          )}
          {cell.status === "completed" ? (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <div>
                <p className="mb-1 text-xs font-medium text-[var(--fg-muted)]">As converted (deterministic)</p>
                <CodeBlock code={cell.before} language="python" />
              </div>
              <div>
                <p className="mb-1 text-xs font-medium text-[var(--fg-muted)]">AI-completed (unverified)</p>
                <CodeBlock code={cell.after} language="python" />
              </div>
            </div>
          ) : (
            <CodeBlock code={cell.before} language="python" />
          )}
        </Card>
      ))}
    </div>
  );
}
