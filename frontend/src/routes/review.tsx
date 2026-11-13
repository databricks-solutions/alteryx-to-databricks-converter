import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ReviewGraph } from "@/components/review/review-graph";
import { HeaderActions } from "@/components/layout/header-actions";
import { CodeBlock } from "@/components/shared/code-block";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { useReview } from "@/hooks/use-review";
import { useToastStore } from "@/stores/toast";
import { api } from "@/lib/api";
import { restore, sameDecisions, sourceKey, toRecord, type LocalDecision } from "@/lib/review-decisions";
import type {
  AISuggestion,
  ConvertOptions,
  FormatId,
  ReviewDecision,
  ReviewDecisionsRecord,
  ReviewNode,
  ReviewSession,
  ReviewStatus,
  WorkflowSource,
} from "@/lib/api";
import { saveAs } from "file-saver";
import { Play, Loader2, Check, X, Pencil, Download, Sparkles, RotateCcw } from "lucide-react";

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

// Local reviewer overlay: node_id -> {decision, edited code, who wrote it}. Kept
// separate from the server session so re-selecting a node preserves in-progress
// edits; saved to the project (or this tab's session) as it changes.

/** One step's AI suggestion as the screen holds it. */
interface SuggestionState {
  loading: boolean;
  result: AISuggestion | null;
  error: string | null;
  hint: string;
}

function effectiveCode(node: ReviewNode, local: LocalDecision | undefined): string {
  if (local?.editedCode != null) return local.editedCode;
  return node.generated_code;
}

/** Node-by-node review of one workflow from the project (picked by the Review
 * step). ``active`` says whether this tab is showing (its header action only
 * appears then); ``onProgress`` reports how many flagged nodes are still open. */
export function ReviewPage({
  source,
  active = true,
  onProgress,
  opts,
  savedReview,
  onSaveReview,
}: {
  source: WorkflowSource | null;
  active?: boolean;
  onProgress?: (p: { needsReview: number; resolved: number; started: boolean }) => void;
  /** The project's conversion options, so steps read as they do in Convert. */
  opts?: ConvertOptions;
  /** Decisions saved from an earlier review of this workflow. */
  savedReview?: ReviewDecisionsRecord | null;
  /** Save the decisions (to the project, or this tab's session). */
  onSaveReview?: (record: ReviewDecisionsRecord) => Promise<void> | void;
}) {
  const [outputFormat, setOutputFormat] = useState<FormatId>("pyspark");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [decisions, setDecisions] = useState<Record<number, LocalDecision>>({});
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  // Who wrote the draft being edited: an AI suggestion, or the reviewer.
  const [draftSource, setDraftSource] = useState<"ai" | "user">("user");
  const [suggestions, setSuggestions] = useState<Record<number, SuggestionState>>({});
  const [restoredNote, setRestoredNote] = useState<string | null>(null);
  const addToast = useToastStore((s) => s.add);
  const aiStatus = useQuery({ queryKey: ["ai-status"], queryFn: api.aiStatus, staleTime: 60_000 });
  const aiEnabled = aiStatus.data?.enabled === true;
  // The saved decisions as of the latest render, read when a session loads.
  const savedRef = useRef(savedReview);
  savedRef.current = savedReview;
  // What was last saved (or restored), so only real changes are written.
  const lastSaved = useRef<Record<number, LocalDecision>>({});
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
    const back = restore(session, savedRef.current);
    setDecisions(back.decisions);
    lastSaved.current = back.decisions;
    setSuggestions({});
    const notes: string[] = [];
    if (back.restored) {
      notes.push(`Picked up ${back.restored} decision${back.restored === 1 ? "" : "s"} from your last review.`);
    }
    if (back.stale) {
      notes.push(
        back.stale === 1
          ? "1 earlier decision was left out because that step's code has changed since."
          : `${back.stale} earlier decisions were left out because those steps' code has changed since.`,
      );
    }
    setRestoredNote(notes.length ? notes.join(" ") : null);
  }, [session]);

  // Save decisions as they change, shortly after the last change.
  useEffect(() => {
    if (!session || !onSaveReview || sameDecisions(decisions, lastSaved.current)) return;
    const handle = window.setTimeout(() => {
      const snapshot = decisions;
      Promise.resolve(onSaveReview(toRecord(session, snapshot)))
        .then(() => {
          lastSaved.current = snapshot;
        })
        .catch((e: unknown) => addToast(e instanceof Error ? e.message : "Couldn't save the review", "error"));
    }, 700);
    return () => window.clearTimeout(handle);
  }, [decisions, session, onSaveReview, addToast]);

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

  useEffect(() => {
    onProgress?.({ needsReview: progress.needsReview, resolved: progress.resolved, started: session != null });
  }, [onProgress, progress.needsReview, progress.resolved, session]);

  const handleReview = () => {
    if (!source) return;
    mutation.mutate({ source, outputFormat, opts });
  };

  // An in-progress edit whose draft diverges from the saved code would be lost
  // on node switch / reset. Detect it and confirm before discarding.
  const hasUnsavedEdit = () =>
    editing && selectedNode != null && draft !== effectiveCode(selectedNode, selectedLocal);
  const confirmDiscard = () =>
    !hasUnsavedEdit() || window.confirm("You have an unsaved edit to this node. Discard it?");

  // A different workflow (or new file content) was picked: start over on it.
  // Keyed on what the source points at, not the object: saving a decision
  // updates the project, which hands this screen a new but equal source.
  const { reset: resetReview } = mutation;
  const key = sourceKey(source);
  useEffect(() => {
    resetReview();
    setSelectedId(null);
    setDecisions({});
    lastSaved.current = {};
    setSuggestions({});
    setRestoredNote(null);
    setEditing(false);
  }, [key, resetReview]);

  const selectNode = (nodeId: number) => {
    if (nodeId === selectedId) return;
    if (!confirmDiscard()) return;
    setSelectedId(nodeId);
    setEditing(false);
  };

  const decide = (nodeId: number, decision: ReviewDecision) => {
    setDecisions((prev) => ({
      ...prev,
      [nodeId]: { decision, editedCode: prev[nodeId]?.editedCode ?? null, source: prev[nodeId]?.source ?? null },
    }));
  };

  /** Edit the step's current code, or (from a suggestion) the given code. */
  const startEdit = (code?: string, from: "ai" | "user" = "user") => {
    if (!selectedNode) return;
    setDraft(code ?? effectiveCode(selectedNode, selectedLocal));
    setDraftSource(code !== undefined ? from : selectedLocal?.source === "ai" ? "ai" : "user");
    setEditing(true);
  };

  const saveEdit = () => {
    if (selectedId == null) return;
    setDecisions((prev) => ({
      ...prev,
      [selectedId]: { decision: "edited", editedCode: draft, source: draftSource },
    }));
    setEditing(false);
  };

  // ── AI suggestions: PySpark, flagged steps ──
  const canSuggest = (node: ReviewNode) =>
    aiEnabled &&
    source != null &&
    session?.output_format === "pyspark" &&
    (node.status === "needs_review" || node.status === "cannot_convert");

  const suggest = (nodeId: number, hint = "") => {
    if (!source) return;
    setSuggestions((prev) => ({ ...prev, [nodeId]: { loading: true, result: null, error: null, hint } }));
    api
      .aiSuggest(source, nodeId, opts, hint)
      .then((result) =>
        setSuggestions((prev) => ({ ...prev, [nodeId]: { loading: false, result, error: null, hint } })),
      )
      .catch((e: unknown) =>
        setSuggestions((prev) => ({
          ...prev,
          [nodeId]: { loading: false, result: null, error: e instanceof Error ? e.message : String(e), hint },
        })),
      );
  };

  const setHint = (nodeId: number, hint: string) =>
    setSuggestions((prev) => ({
      ...prev,
      [nodeId]: { ...(prev[nodeId] ?? { loading: false, result: null, error: null }), hint },
    }));

  const discardSuggestion = (nodeId: number) =>
    setSuggestions((prev) => {
      const next = { ...prev };
      delete next[nodeId];
      return next;
    });

  const takeSuggestion = (nodeId: number, code: string) => {
    setDecisions((prev) => ({ ...prev, [nodeId]: { decision: "edited", editedCode: code, source: "ai" } }));
    discardSuggestion(nodeId);
  };

  const editSuggestion = (nodeId: number, code: string) => {
    startEdit(code, "ai");
    discardSuggestion(nodeId);
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
      {!session && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
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
            <Button onClick={handleReview} disabled={!source || mutation.isPending}>
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
                {progress.resolved} / {progress.needsReview} flagged nodes reviewed
              </span>
            </div>
            {active && (
              <HeaderActions>
                <Button size="sm" variant="secondary" onClick={handleExport} disabled={session.nodes.length === 0}>
                  <Download className="h-4 w-4" />
                  Download reviewed code
                </Button>
              </HeaderActions>
            )}
            <Progress value={progress.pct} />
            {restoredNote && <p className="mt-2 text-xs text-[var(--fg-muted)]">{restoredNote}</p>}
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
                        {selectedLocal.decision === "edited" && selectedLocal.source === "ai"
                          ? "AI suggestion used"
                          : selectedLocal.decision}
                      </Badge>
                    )}
                    <span className="text-xs text-[var(--fg-muted)]">
                      {selectedNode.status === "cannot_convert"
                        ? "Not converted"
                        : selectedNode.unfinished
                          ? "Not finished: the converter left a TODO in this step"
                          : `${(selectedNode.confidence * 100).toFixed(0)}% mapping confidence`}
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
                      {draftSource === "ai" && (
                        <p className="text-xs text-[var(--fg-muted)]">
                          Editing the AI suggestion. It hasn't been run or verified.
                        </p>
                      )}
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
                      <Button size="sm" variant="secondary" onClick={() => startEdit()}>
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
                  {!editing && (
                    <SuggestPanel
                      node={selectedNode}
                      available={canSuggest(selectedNode)}
                      aiEnabled={aiEnabled}
                      format={session.output_format}
                      state={suggestions[selectedNode.node_id]}
                      onSuggest={(hint) => suggest(selectedNode.node_id, hint)}
                      onHint={(hint) => setHint(selectedNode.node_id, hint)}
                      onUse={(code) => takeSuggestion(selectedNode.node_id, code)}
                      onEdit={(code) => editSuggestion(selectedNode.node_id, code)}
                      onDiscard={() => discardSuggestion(selectedNode.node_id)}
                    />
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

/** "Suggest code" for one flagged step: ask the model, then use, edit or discard
 * what it wrote. Nothing changes until the reviewer picks. */
function SuggestPanel({
  node,
  available,
  aiEnabled,
  format,
  state,
  onSuggest,
  onHint,
  onUse,
  onEdit,
  onDiscard,
}: {
  node: ReviewNode;
  available: boolean;
  aiEnabled: boolean;
  format: string;
  state: SuggestionState | undefined;
  onSuggest: (hint: string) => void;
  onHint: (hint: string) => void;
  onUse: (code: string) => void;
  onEdit: (code: string) => void;
  onDiscard: () => void;
}) {
  const flagged = node.status === "needs_review" || node.status === "cannot_convert";
  if (!aiEnabled || !flagged) return null;
  if (!available) {
    return (
      <p className="text-xs text-[var(--fg-muted)]">
        {format === "pyspark"
          ? "AI suggestions need the workflow from the project."
          : "AI suggestions are for PySpark. Pick PySpark as the target format to ask for one."}
      </p>
    );
  }
  const hint = state?.hint ?? "";
  const result = state?.result ?? null;

  if (!state || (!state.loading && !result && !state.error)) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" onClick={() => onSuggest(hint)}>
          <Sparkles className="h-4 w-4" />
          Suggest code with AI
        </Button>
        <span className="text-xs text-[var(--fg-muted)]">A model drafts this step; you decide whether to use it.</span>
      </div>
    );
  }
  if (state.loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-[var(--fg-muted)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        Asking the model for this step. This usually takes a few seconds.
      </div>
    );
  }

  const retry = (
    <div className="space-y-2">
      <label htmlFor={`hint-${node.node_id}`} className="block text-xs text-[var(--fg-muted)]">
        Add a note for the model (optional), for example which columns to join on
      </label>
      <textarea
        id={`hint-${node.node_id}`}
        value={hint}
        maxLength={2000}
        onChange={(e) => onHint(e.target.value)}
        rows={2}
        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-2 text-sm text-[var(--fg)]"
      />
      <Button size="sm" variant="secondary" onClick={() => onSuggest(hint)}>
        <RotateCcw className="h-4 w-4" />
        Try again
      </Button>
    </div>
  );

  if (state.error || !result) {
    return (
      <div className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3">
        <p className="text-sm text-[var(--fg)]">The suggestion didn't come through: {state.error}</p>
        {retry}
      </div>
    );
  }
  if (result.status !== "completed" || !result.code) {
    return (
      <div className="space-y-2 rounded-lg border border-warning/30 bg-warning/5 p-3">
        <p className="text-sm text-[var(--fg)]">
          {result.status === "skipped" ? "No suggestion for this step: " : "The model's code wasn't usable: "}
          {result.reason}
        </p>
        {result.status === "failed" ? retry : (
          <Button size="sm" variant="secondary" onClick={onDiscard}>
            Close
          </Button>
        )}
      </div>
    );
  }
  return (
    <div className="space-y-2 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-3">
      <p className="flex items-center gap-1.5 text-sm font-medium text-[var(--fg)]">
        <Sparkles className="h-4 w-4" />
        AI suggestion, not run or verified
      </p>
      <CodeBlock code={result.code} language="python" wrap />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => onUse(result.code!)}>
          <Check className="h-4 w-4" />
          Use it
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onEdit(result.code!)}>
          <Pencil className="h-4 w-4" />
          Edit it
        </Button>
        <Button size="sm" variant="secondary" onClick={onDiscard}>
          <X className="h-4 w-4" />
          Discard
        </Button>
      </div>
      {retry}
    </div>
  );
}
