import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { FileDropzone } from "@/components/shared/file-dropzone";
import { ReviewGraph } from "@/components/review/review-graph";
import { CodeBlock } from "@/components/shared/code-block";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { useReview } from "@/hooks/use-review";
import { useToastStore } from "@/stores/toast";
import type {
  FormatId,
  ReviewDecision,
  ReviewNode,
  ReviewSession,
  ReviewStatus,
} from "@/lib/api";
import { saveAs } from "file-saver";
import { Play, Loader2, RotateCcw, Check, X, Pencil, Download } from "lucide-react";

const FORMAT_LANGUAGE: Record<FormatId, "python" | "sql" | "json"> = {
  pyspark: "python",
  dlt: "python",
  sql: "sql",
  lakeflow: "sql",
  designer: "json",
};

const STATUS_LABEL: Record<ReviewStatus, string> = {
  auto_accepted: "Auto-accepted",
  needs_review: "Needs review",
  cannot_convert: "Cannot convert",
};

const STATUS_VARIANT: Record<ReviewStatus, "success" | "warning" | "destructive"> = {
  auto_accepted: "success",
  needs_review: "warning",
  cannot_convert: "destructive",
};

const DECISION_VARIANT: Record<ReviewDecision, "default" | "success" | "destructive" | "secondary"> = {
  pending: "secondary",
  accepted: "success",
  edited: "success",
  rejected: "destructive",
};

// Local reviewer overlay: node_id -> {decision, edited_code}. Kept separate
// from the server session so re-selecting a node preserves in-progress edits.
interface LocalDecision {
  decision: ReviewDecision;
  editedCode: string | null;
}

function effectiveCode(node: ReviewNode, local: LocalDecision | undefined): string {
  if (local?.editedCode != null) return local.editedCode;
  return node.generated_code;
}

export function ReviewPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [outputFormat, setOutputFormat] = useState<FormatId>("pyspark");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [decisions, setDecisions] = useState<Record<number, LocalDecision>>({});
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const addToast = useToastStore((s) => s.add);
  const mutation = useReview();
  const session: ReviewSession | undefined = mutation.data;

  // Select the first node (prefer the first that needs review) on new data.
  useEffect(() => {
    if (!session || session.nodes.length === 0) {
      setSelectedId(null);
      return;
    }
    const firstNeedsReview = session.nodes.find(
      (n) => n.status === "needs_review" || n.status === "cannot_convert",
    );
    setSelectedId((firstNeedsReview ?? session.nodes[0]).node_id);
    setDecisions({});
  }, [session]);

  const selectedNode = useMemo(
    () => session?.nodes.find((n) => n.node_id === selectedId) ?? null,
    [session, selectedId],
  );
  const selectedLocal = selectedId != null ? decisions[selectedId] : undefined;

  // Progress: how many needs-review/cannot-convert nodes have a decision.
  const progress = useMemo(() => {
    if (!session) return { needsReview: 0, resolved: 0, pct: 0 };
    const needsReview = session.nodes.filter(
      (n) => n.status === "needs_review" || n.status === "cannot_convert",
    );
    const resolved = needsReview.filter(
      (n) => (decisions[n.node_id]?.decision ?? "pending") !== "pending",
    ).length;
    const pct = needsReview.length === 0 ? 100 : (resolved / needsReview.length) * 100;
    return { needsReview: needsReview.length, resolved, pct };
  }, [session, decisions]);

  const handleReview = () => {
    if (files.length === 0) return;
    mutation.mutate({ file: files[0], outputFormat });
  };

  const handleReset = () => {
    mutation.reset();
    setFiles([]);
    setSelectedId(null);
    setDecisions({});
    setEditing(false);
  };

  const selectNode = (nodeId: number) => {
    setSelectedId(nodeId);
    setEditing(false);
  };

  const decide = (nodeId: number, decision: ReviewDecision) => {
    setDecisions((prev) => ({
      ...prev,
      [nodeId]: { decision, editedCode: prev[nodeId]?.editedCode ?? null },
    }));
  };

  const startEdit = () => {
    if (!selectedNode) return;
    setDraft(effectiveCode(selectedNode, selectedLocal));
    setEditing(true);
  };

  const saveEdit = () => {
    if (selectedId == null) return;
    setDecisions((prev) => ({
      ...prev,
      [selectedId]: { decision: "edited", editedCode: draft },
    }));
    setEditing(false);
  };

  const handleExport = () => {
    if (!session) return;
    // Nodes arrive in topological order; concatenate each node's effective
    // code (reviewer edit if any) in that order, skipping rejected nodes.
    const parts: string[] = [];
    for (const node of session.nodes) {
      const local = decisions[node.node_id];
      if (local?.decision === "rejected") continue;
      const code = effectiveCode(node, local).trimEnd();
      if (code) parts.push(code);
    }
    const ext = FORMAT_LANGUAGE[session.output_format] === "python" ? "py" : FORMAT_LANGUAGE[session.output_format];
    const blob = new Blob([parts.join("\n\n")], { type: "text/plain;charset=utf-8" });
    saveAs(blob, `${session.workflow_name}-reviewed.${ext}`);
    addToast("Exported reviewed workflow", "success");
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Review Workspace"
        description="Inspect each node's generated code beside the workflow canvas, then accept, edit, or reject before exporting"
      >
        {session && (
          <Button variant="secondary" size="sm" onClick={handleReset}>
            <RotateCcw className="h-4 w-4" />
            Review Another
          </Button>
        )}
      </PageHeader>

      {!session && (
        <div className="space-y-4">
          <FileDropzone files={files} onFilesChange={setFiles} />
          <div className="flex items-center gap-3">
            <label htmlFor="review-format" className="text-sm text-[var(--fg-muted)]">
              Target format
            </label>
            <select
              id="review-format"
              value={outputFormat}
              onChange={(e) => setOutputFormat(e.target.value as FormatId)}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-1.5 text-sm text-[var(--fg)]"
            >
              <option value="pyspark">PySpark</option>
              <option value="dlt">Spark Declarative Pipelines</option>
              <option value="sql">Databricks SQL</option>
              <option value="lakeflow">Lakeflow</option>
            </select>
            <Button onClick={handleReview} disabled={files.length === 0 || mutation.isPending}>
              {mutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              Start Review
            </Button>
          </div>
          {mutation.isError && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              {mutation.error.message}
            </div>
          )}
        </div>
      )}

      {session && (
        <div className="space-y-4">
          {/* Progress bar */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <div className="flex items-center justify-between mb-2 text-sm">
              <span className="font-medium text-[var(--fg)]">
                {progress.resolved} / {progress.needsReview} nodes reviewed
              </span>
              <Button
                size="sm"
                variant="secondary"
                onClick={handleExport}
                disabled={session.nodes.length === 0}
              >
                <Download className="h-4 w-4" />
                Export
              </Button>
            </div>
            <Progress value={progress.pct} />
          </div>

          {/* Two synced panes */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Canvas */}
            <div className="h-[70vh] rounded-xl border border-[var(--border)] overflow-hidden bg-[var(--bg-card)]">
              <ReviewGraph
                nodes={session.nodes}
                edges={session.edges}
                selectedId={selectedId}
                onNodeSelect={selectNode}
              />
            </div>

            {/* Code + controls */}
            <div className="flex flex-col gap-3">
              {selectedNode ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-[var(--fg)]">
                      {selectedNode.tool_type}
                    </span>
                    <span className="text-xs text-[var(--fg-muted)]">
                      node {selectedNode.node_id}
                    </span>
                    <Badge variant={STATUS_VARIANT[selectedNode.status]}>
                      {STATUS_LABEL[selectedNode.status]}
                    </Badge>
                    {selectedLocal && selectedLocal.decision !== "pending" && (
                      <Badge variant={DECISION_VARIANT[selectedLocal.decision]}>
                        {selectedLocal.decision}
                      </Badge>
                    )}
                    <span className="text-xs text-[var(--fg-muted)]">
                      {(selectedNode.confidence * 100).toFixed(0)}% confidence
                    </span>
                  </div>

                  {selectedNode.annotation && (
                    <p className="text-sm text-[var(--fg-muted)]">{selectedNode.annotation}</p>
                  )}

                  {selectedNode.warnings.length > 0 && (
                    <div className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-xs text-[var(--fg)]">
                      <ul className="list-disc pl-4 space-y-0.5">
                        {selectedNode.warnings.map((w, i) => (
                          <li key={i}>{w}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {editing ? (
                    <div className="space-y-2">
                      <textarea
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        spellCheck={false}
                        className="w-full h-[46vh] rounded-xl border border-[var(--border)] bg-[var(--bg-sidebar)] p-3 font-mono text-sm text-[var(--fg)]"
                      />
                      <div className="flex gap-2">
                        <Button size="sm" onClick={saveEdit}>
                          <Check className="h-4 w-4" />
                          Save edit
                        </Button>
                        <Button size="sm" variant="secondary" onClick={() => setEditing(false)}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <CodeBlock
                      code={effectiveCode(selectedNode, selectedLocal)}
                      language={FORMAT_LANGUAGE[session.output_format]}
                    />
                  )}

                  {!editing && (
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => decide(selectedNode.node_id, "accepted")}
                      >
                        <Check className="h-4 w-4" />
                        Accept
                      </Button>
                      <Button size="sm" variant="secondary" onClick={startEdit}>
                        <Pencil className="h-4 w-4" />
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => decide(selectedNode.node_id, "rejected")}
                      >
                        <X className="h-4 w-4" />
                        Reject
                      </Button>
                    </div>
                  )}
                </>
              ) : (
                <p className="text-sm text-[var(--fg-muted)]">
                  Select a node in the canvas to review its generated code.
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
