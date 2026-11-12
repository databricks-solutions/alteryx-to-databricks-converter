import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { saveAs } from "file-saver";
import { StepHeader } from "@/components/layout/step-header";
import { CodeBlock } from "@/components/shared/code-block";
import { WorkflowPicker, defaultWorkflowId } from "@/components/shared/workflow-picker";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useProjectContext } from "@/hooks/use-project-context";
import { useConvertOptions } from "@/hooks/use-convert-options";
import { useToastStore } from "@/stores/toast";
import { api, type AICompletion, type CellCompletion, type MigrationContext } from "@/lib/api";
import { EmptyProject } from "@/routes/assess-hub";
import { Sparkles, Download, Loader2, FileText, AlertTriangle, CheckCircle2 } from "lucide-react";

const GAP_LABEL: Record<string, string> = {
  unsupported_tool: "Unsupported tool",
  todo: "TODO left in the code",
  review_warning: "Needs review",
  graph: "Workflow structure",
};

const CELL_VARIANT: Record<CellCompletion["status"], "success" | "destructive" | "secondary"> = {
  completed: "success",
  failed: "destructive",
  skipped: "secondary",
};

/**
 * Step 6 (optional). The only place in the app that produces non-deterministic
 * output. For one converted workflow it shows what the converter couldn't
 * finish, and can have a model fill in just those cells — as a separate,
 * clearly marked copy of the PySpark notebook. The deterministic output from
 * Convert is never changed.
 */
export function AiCompletionPage() {
  const ctx = useProjectContext();
  const opts = useConvertOptions();
  const addToast = useToastStore((s) => s.add);
  const status = useQuery({ queryKey: ["ai-status"], queryFn: api.aiStatus, staleTime: 60_000 });
  const enabled = status.data?.enabled ?? false;
  const [workflowId, setWorkflowId] = useState<string | null>(() => defaultWorkflowId(ctx.workflows, "deployed"));
  const workflow = ctx.workflows.find((w) => w.id === workflowId) ?? null;

  useEffect(() => {
    if (workflowId == null && ctx.workflows.length > 0) setWorkflowId(defaultWorkflowId(ctx.workflows, "deployed"));
  }, [workflowId, ctx.workflows]);

  const source = workflowId ? ctx.workflowSource(workflowId) : null;

  // What needs work — deterministic, so it works without AI configured.
  const gaps = useQuery<MigrationContext>({
    queryKey: ["ai-gaps", ctx.projectId, workflowId, ctx.signature, opts.catalogName, opts.schemaName],
    queryFn: () => api.aiGaps(source!, opts),
    enabled: source != null,
    retry: false,
  });

  const complete = useMutation<AICompletion, Error>({
    mutationFn: () => api.aiComplete(source!, opts),
  });
  const notes = useMutation<string, Error>({
    mutationFn: () => api.aiNotes(source!, opts),
    onSuccess: (markdown) => {
      const name = `${gaps.data?.workflow_name ?? "workflow"}_suggestions.md`;
      saveAs(new Blob([markdown], { type: "text/markdown;charset=utf-8" }), name);
      addToast("Suggestions notes downloaded", "success");
    },
    onError: (e) => addToast(e.message, "error"),
  });

  // A new pick starts clean.
  const { reset: resetComplete } = complete;
  useEffect(() => {
    resetComplete();
  }, [workflowId, resetComplete]);

  const result = complete.data;
  const download = () => {
    if (!result) return;
    saveAs(new Blob([result.content], { type: "text/x-python;charset=utf-8" }), result.filename);
  };

  return (
    <div>
      <StepHeader slug="ai-completion">
        {result && (
          <Button size="sm" onClick={download}>
            <Download className="h-4 w-4" />
            Download {result.filename}
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
              model proposes code for just the parts the converter couldn't finish (unsupported tools, TODOs), and
              you get it as a <strong className="text-[var(--fg)]">separate copy</strong> of the PySpark notebook
              with every AI-written cell marked.
            </p>
            <p>
              Nothing here has been run or verified, and your deterministic files aren't changed. Review every marked
              cell before you use it. PySpark notebooks only, for now.
            </p>
          </div>
        </div>

        {!status.isLoading && !enabled && (
          <div className="rounded-xl border border-warning/30 bg-warning/5 p-4 text-sm">
            <p className="font-medium text-[var(--fg)]">AI isn't set up on this server</p>
            <p className="mt-1 text-[var(--fg-muted)]">
              It needs a Databricks Foundation Model API endpoint: set{" "}
              <code className="rounded bg-[var(--bg-sidebar)] px-1 py-0.5 font-mono text-xs">A2D_FMAPI_ENDPOINT</code>{" "}
              (and{" "}
              <code className="rounded bg-[var(--bg-sidebar)] px-1 py-0.5 font-mono text-xs">A2D_FMAPI_TOKEN</code>{" "}
              if it needs a token) and restart. You can still see below what a completion would cover.
            </p>
          </div>
        )}

        {ctx.workflows.length === 0 ? (
          <EmptyProject />
        ) : (
          <>
            <WorkflowPicker workflows={ctx.workflows} value={workflowId} onChange={setWorkflowId} />

            {/* What the converter couldn't finish */}
            {gaps.isLoading && <Skeleton className="h-32 rounded-xl" />}
            {gaps.error && <p className="text-sm text-destructive">{gaps.error.message}</p>}
            {gaps.data && (
              <Card className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-sm font-semibold text-[var(--fg)]">What the converter couldn't finish</h2>
                  <span className="text-xs text-[var(--fg-muted)]">
                    {gaps.data.summary.total_gaps} item(s)
                    {gaps.data.coverage != null && ` · ${gaps.data.coverage.toFixed(0)}% deterministic coverage`}
                  </span>
                </div>
                {gaps.data.gaps.length === 0 ? (
                  <p className="flex items-center gap-2 text-sm text-[var(--fg-muted)]">
                    <CheckCircle2 className="h-4 w-4 text-success" />
                    Nothing. Every node in {workflow?.file_name ?? "this workflow"} converted deterministically, so
                    there's nothing for a model to fill in.
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
                {enabled && gaps.data.gaps.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Button onClick={() => complete.mutate()} disabled={complete.isPending}>
                      {complete.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                      Generate AI-completed version
                    </Button>
                    <Button variant="secondary" onClick={() => notes.mutate()} disabled={notes.isPending}>
                      {notes.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                      Download suggestions notes (.md)
                    </Button>
                  </div>
                )}
                {complete.isPending && (
                  <p className="text-xs text-[var(--fg-muted)]" role="status" aria-live="polite">
                    Asking the model for each cell that needs work. This can take a minute or two for a large workflow.
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
          {summary.completed} of {summary.cells_needing_work} cell(s) completed by AI
          {summary.failed > 0 && ` · ${summary.failed} kept as converted (the AI code didn't pass checks)`}
          {summary.skipped > 0 && ` · ${summary.skipped} skipped`}
        </span>
        <span className="ml-auto text-xs text-[var(--fg-muted)]">
          The deterministic notebook is still <code>{result.deterministic_filename}</code>, unchanged.
        </span>
      </Card>

      {result.cells.map((cell, i) => (
        <Card key={i} className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-[var(--fg)]">
              Step {cell.node_id ?? "?"}
              {cell.tool_type ? ` · ${cell.tool_type}` : ""}
            </span>
            <Badge variant={CELL_VARIANT[cell.status]}>
              {cell.status === "completed" ? "AI-completed" : cell.status === "failed" ? "Kept as converted" : "Skipped"}
            </Badge>
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
