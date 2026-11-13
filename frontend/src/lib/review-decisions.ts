import type { FormatId, ReviewDecision, ReviewDecisionsRecord, ReviewSession, WorkflowSource } from "@/lib/api";

/** A reviewer's call on one step, as the Review screen holds it. */
export interface LocalDecision {
  decision: ReviewDecision;
  editedCode: string | null;
  /** Who wrote the edited code: an AI suggestion the reviewer used, or the reviewer. */
  source?: "ai" | "user" | null;
}

/** A short, stable hash of a step's generated code (FNV-1a, 32-bit, hex). Only
 * used to tell whether the code a decision was made on has changed. */
export function codeHash(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

/** The decisions to save for a session: every step with a decision. */
export function toRecord(
  session: ReviewSession,
  decisions: Record<number, LocalDecision>,
  now: Date = new Date(),
): ReviewDecisionsRecord {
  const nodes: ReviewDecisionsRecord["nodes"] = {};
  for (const node of session.nodes) {
    const d = decisions[node.node_id];
    if (!d || d.decision === "pending") continue;
    nodes[String(node.node_id)] = {
      decision: d.decision,
      code: d.editedCode,
      source: d.source ?? null,
      base: codeHash(node.generated_code),
    };
  }
  return { output_format: session.output_format as FormatId, nodes, saved_at: now.toISOString() };
}

/** Saved decisions that still apply to this session: same output format, and the
 * step's generated code unchanged since the decision. `stale` counts the ones
 * dropped because the step's code changed (re-converted with other options, or
 * a new version of the file). */
export function restore(
  session: ReviewSession,
  record: ReviewDecisionsRecord | null | undefined,
): { decisions: Record<number, LocalDecision>; restored: number; stale: number } {
  const decisions: Record<number, LocalDecision> = {};
  if (!record || record.output_format !== session.output_format) return { decisions, restored: 0, stale: 0 };
  let restored = 0;
  let stale = 0;
  const byId = new Map(session.nodes.map((n) => [String(n.node_id), n]));
  for (const [id, saved] of Object.entries(record.nodes ?? {})) {
    const node = byId.get(id);
    if (!node || codeHash(node.generated_code) !== saved.base) {
      stale++;
      continue;
    }
    decisions[node.node_id] = { decision: saved.decision, editedCode: saved.code, source: saved.source };
    restored++;
  }
  return { decisions, restored, stale };
}

/** True when two decision sets would save the same record (ignores the time). */
export function sameDecisions(a: Record<number, LocalDecision>, b: Record<number, LocalDecision>): boolean {
  const norm = (d: Record<number, LocalDecision>) =>
    JSON.stringify(
      Object.entries(d)
        .filter(([, v]) => v.decision !== "pending")
        .sort(([x], [y]) => Number(x) - Number(y))
        .map(([k, v]) => [k, v.decision, v.editedCode, v.source ?? null]),
    );
  return norm(a) === norm(b);
}

/** What a source points at: a saved project's workflow, or a session file (and
 * its macros) by name, size and modification time. Equal for equal sources. */
export function sourceKey(source: WorkflowSource | null): string {
  if (!source) return "";
  if ("file" in source) {
    const f = (x: File) => `${x.name}:${x.size}:${x.lastModified}`;
    return [f(source.file), ...(source.macros ?? []).map(f).sort()].join("|");
  }
  return `${source.projectId}/${source.workflowId}`;
}
