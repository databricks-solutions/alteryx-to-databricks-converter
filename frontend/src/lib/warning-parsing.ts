/**
 * Parse raw warning strings emitted by the converter / generators into a
 * structured form so the UI can render plain-English copy and group related
 * warnings together.
 *
 * The backend currently emits free-form strings (e.g.
 *   "Unsupported node 765: No converter for tool type: Unknown"
 *   "No DLT generator for DynamicRenameNode (node 808)"
 *   "Filter expression fallback for node 679"
 *   "Graph has 2 disconnected data components: [4, 14, ...], [765, 833]"
 *   "DynamicRename node 808 (from-input mode): manual DLT review needed"
 *   "DynamicRename node 452 (FirstRow mode): manual SQL rewrite needed"
 * ).
 *
 * This module is the single place that knows about those formats. It is pure
 * (no React, no DOM) so it can be unit-tested or reused on the server side
 * later without changes.
 */
import { formatLabel } from "@/lib/constants";

export type WarningKind =
  /** Tool we don't have a converter for at all — code is missing. */
  | "unsupported_tool"
  /** Generator (PySpark / DLT / SQL / Lakeflow) doesn't have a visitor for an
   *  IR node, so the format emits a placeholder comment. */
  | "missing_generator"
  /** Expression couldn't be parsed/translated — generator emitted a
   *  best-effort fallback (raw expr_str, simplified logic, etc.). */
  | "expression_fallback"
  /** Input/Output node references a local or UNC path that won't resolve on
   *  Databricks compute — needs migration to cloud storage / UC volumes. */
  | "local_path"
  /** DAG has multiple disconnected components — informational, not an error. */
  | "disconnected_components"
  /** Anything we couldn't classify; rendered verbatim. */
  | "other";

/** Severity for the headline / sorting; lower = more benign. */
export type WarningSeverity = "info" | "review" | "blocker";

export interface ParsedWarning {
  kind: WarningKind;
  severity: WarningSeverity;
  /** Original string, kept for debugging / copy-paste. */
  raw: string;
  /** Pre-rendered short title in plain English. */
  title: string;
  /** Pre-rendered explanation paragraph. */
  detail: string;
  /** Node id if the warning references one specific node. */
  nodeId?: number;
  /** Tool / IR node class name if present (e.g. "DynamicRenameNode"). */
  tool?: string;
  /** Format id this warning is specific to ("dlt", "sql", ...) if any. */
  generator?: string;
  /** For disconnected_components: list of component sizes / sample ids. */
  components?: number[][];
}

// PySpark generator emits `Unsupported node N (Tool): No converter ...` with
// the tool name in parens; SQL/DLT emit the older `Unsupported node N: ...`
// shape. Accept both — the parens group is optional and non-capturing for the
// outer wrapper but the tool name itself is captured when present.
const RE_UNSUPPORTED =
  /^Unsupported node (\d+)(?:\s*\(([^)]+)\))?:\s*No converter for tool type:\s*(.+?)\s*$/i;
const RE_NO_GENERATOR =
  /^No (PySpark|DLT|SQL|Lakeflow)\s+generator\s+for\s+(\w+)\s*\(node\s*(\d+)\)/i;
const RE_EXPR_FALLBACK =
  /^(\w+)\s+expression\s+fallback\s+for\s+node\s+(\d+)/i;
const RE_DISCONNECTED =
  /^Graph has (\d+)\s+disconnected\s+data\s+components?:\s*(.*)$/i;
// Generators flag local/UNC paths that need to be migrated to cloud storage
// (UC volumes, S3, ADLS). Informational, not a blocker — but it IS something
// the user must address before running.
const RE_LOCAL_PATH =
  /^(Input|Output) node (\d+):\s*path\s*'(.+?)'\s*is a local\/UNC path/i;
// DLT/SQL/PySpark generators emit this when a DynamicRename node can't be
// auto-translated (the rename map is data-driven; the generator produces a
// placeholder). All three generators emit the same shape now:
//   "DynamicRename node 808 (from-input mode): manual DLT review needed"
//   "DynamicRename node 452 (Formula mode): manual SQL rewrite needed"
//   "DynamicRename node 809 (Formula mode): manual PySpark rewrite needed"
// Source: src/a2d/generators/{sql,dlt,pyspark}.py
const RE_DYNAMIC_RENAME =
  /^DynamicRename node (\d+) \(([^)]+) mode\):\s*(.+?)$/i;
// Join visitor flags a join with no resolvable keys (the user must fill in
// the join condition manually). Emitted by pyspark.py:1014 and analogous
// SQL/DLT handlers. E.g.:
//   "Join node 286: no join keys found — manual condition required"
const RE_JOIN_NO_KEYS =
  /^Join node (\d+):\s*no join keys found\s*[—\-]+\s*manual condition required/i;

/** Strip the trailing "Node" suffix from IR class names for friendlier copy. */
function prettyTool(tool: string): string {
  return tool.replace(/Node$/, "");
}

/** Try to parse "[1, 2, 3], [4, 5]" → [[1,2,3], [4,5]]. */
function parseComponentList(s: string): number[][] {
  const out: number[][] = [];
  const re = /\[([^\]]*)\]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s)) !== null) {
    const ids = m[1]
      .split(",")
      .map((x) => Number(x.trim()))
      .filter((n) => Number.isFinite(n));
    if (ids.length) out.push(ids);
  }
  return out;
}

export function parseWarning(raw: string): ParsedWarning {
  const trimmed = raw.trim();

  let m = RE_UNSUPPORTED.exec(trimmed);
  if (m) {
    const nodeId = Number(m[1]);
    // m[2] is the optional parenthesized tool name (PySpark style); m[3] is
    // the tool name from `No converter for tool type: X`. Prefer the parens
    // form when present since it's typically the friendlier name.
    const tool = m[2] || m[3];
    return {
      kind: "unsupported_tool",
      severity: "blocker",
      raw,
      nodeId,
      tool,
      title: `Node ${nodeId} (${tool}) — no converter`,
      detail:
        `a2d does not yet support the Alteryx tool "${tool}". The generated ` +
        `code skips this node, so the dataflow downstream of node ${nodeId} ` +
        `will be incomplete. You must replace this step manually.`,
    };
  }

  m = RE_NO_GENERATOR.exec(trimmed);
  if (m) {
    const generator = m[1].toLowerCase();
    const tool = m[2];
    const nodeId = Number(m[3]);
    return {
      kind: "missing_generator",
      severity: "review",
      raw,
      nodeId,
      tool,
      generator,
      title: `Node ${nodeId} (${prettyTool(tool)}) — ${formatLabel(generator)} generator missing`,
      detail:
        `a2d understood this Alteryx tool but the ${formatLabel(generator)} ` +
        `generator does not yet emit code for it. The output contains a ` +
        `comment placeholder. Other formats (e.g. PySpark) may still cover ` +
        `this node — check the other tabs.`,
    };
  }

  m = RE_EXPR_FALLBACK.exec(trimmed);
  if (m) {
    const tool = m[1];
    const nodeId = Number(m[2]);
    return {
      kind: "expression_fallback",
      severity: "review",
      raw,
      nodeId,
      tool,
      title: `Node ${nodeId} (${tool}) — expression fallback`,
      detail:
        `a2d couldn't fully translate one of the Alteryx expressions on this ` +
        `${tool} node. It emitted a best-effort translation; verify the ` +
        `logic before running.`,
    };
  }

  m = RE_LOCAL_PATH.exec(trimmed);
  if (m) {
    const direction = m[1]; // "Input" | "Output"
    const nodeId = Number(m[2]);
    const path = m[3];
    return {
      kind: "local_path",
      severity: "review",
      raw,
      nodeId,
      title: `Node ${nodeId} (${direction}) — local/UNC path`,
      detail:
        `This ${direction.toLowerCase()} references a local or UNC path ` +
        `("${path}") which Databricks compute cannot read. Migrate the file ` +
        `to a cloud location (Unity Catalog volume, S3, ADLS, GCS) and ` +
        `update the path in the generated code before running.`,
    };
  }

  m = RE_DISCONNECTED.exec(trimmed);
  if (m) {
    const count = Number(m[1]);
    const components = parseComponentList(m[2]);
    return {
      kind: "disconnected_components",
      severity: "info",
      raw,
      components,
      title: `${count} disconnected dataflows`,
      detail:
        `Your workflow has ${count} independent dataflows that don't share ` +
        `nodes. This is normal in complex workflows but means some branches ` +
        `don't feed into a final output — double-check that's intentional.`,
    };
  }

  m = RE_DYNAMIC_RENAME.exec(trimmed);
  if (m) {
    const nodeId = Number(m[1]);
    const mode = m[2];
    // m[3] is the trailing detail (e.g. "manual SQL rewrite needed").
    // We classify as missing_generator so the warning lands in "Manual review
    // needed" rather than the generic "Other" bucket.
    return {
      kind: "missing_generator",
      severity: "review",
      raw,
      nodeId,
      tool: "DynamicRename",
      title: `Node ${nodeId} (DynamicRename, ${mode} mode) — needs manual rewrite`,
      detail:
        `The rename map is data-driven, so a2d emitted a placeholder rather ` +
        `than a guess. Review the generated code for this node and supply ` +
        `the correct rename rules manually.`,
    };
  }

  m = RE_JOIN_NO_KEYS.exec(trimmed);
  if (m) {
    const nodeId = Number(m[1]);
    return {
      kind: "missing_generator",
      severity: "review",
      raw,
      nodeId,
      tool: "Join",
      title: `Node ${nodeId} (Join) — no join keys resolved`,
      detail:
        `a2d couldn't infer the join keys from the Alteryx workflow. The ` +
        `generated code uses ${"`F.lit(True)`"} (a cross-join placeholder) — ` +
        `replace it with the correct join condition before running.`,
    };
  }

  // Fallback: keep the original string but tag as review-level.
  return {
    kind: "other",
    severity: "review",
    raw,
    title: trimmed,
    detail:
      `a2d emitted this warning but the UI doesn't have a structured ` +
      `template for it yet. Use the original message for context.`,
  };
}

/** Convenience: parse a list, dropping empties. */
export function parseWarnings(raw: ReadonlyArray<string>): ParsedWarning[] {
  return raw.filter((s) => s && s.trim().length > 0).map(parseWarning);
}

export interface CategorizedWarnings {
  unsupported: ParsedWarning[];
  review: ParsedWarning[];
  graph: ParsedWarning[];
  other: ParsedWarning[];
  /** Total count across all buckets. */
  total: number;
  /** Count of node ids that need any kind of manual attention
   *  (unsupported + missing_generator + expression_fallback). */
  manualReviewNodeCount: number;
}

/** Group parsed warnings by user-facing bucket. */
export function categorizeWarnings(
  parsed: ReadonlyArray<ParsedWarning>,
): CategorizedWarnings {
  const unsupported: ParsedWarning[] = [];
  const review: ParsedWarning[] = [];
  const graph: ParsedWarning[] = [];
  const other: ParsedWarning[] = [];
  const reviewNodeIds = new Set<number>();

  for (const w of parsed) {
    switch (w.kind) {
      case "unsupported_tool":
        unsupported.push(w);
        if (w.nodeId !== undefined) reviewNodeIds.add(w.nodeId);
        break;
      case "missing_generator":
      case "expression_fallback":
      case "local_path":
        review.push(w);
        if (w.nodeId !== undefined) reviewNodeIds.add(w.nodeId);
        break;
      case "disconnected_components":
        graph.push(w);
        break;
      case "other":
      default:
        other.push(w);
        break;
    }
  }

  return {
    unsupported,
    review,
    graph,
    other,
    total: parsed.length,
    manualReviewNodeCount: reviewNodeIds.size,
  };
}

/**
 * Combine workflow-level warnings with the warnings for a single format and
 * categorize the union. Useful for per-format tabs so users see ALL relevant
 * issues without having to scroll back up.
 */
export function categorizeForFormat(
  workflowWarnings: ReadonlyArray<string>,
  formatWarnings: ReadonlyArray<string>,
): CategorizedWarnings {
  const all = [
    ...parseWarnings(workflowWarnings),
    ...parseWarnings(formatWarnings),
  ];
  return categorizeWarnings(all);
}

/**
 * Aggregate warnings across the workflow level AND every per-format warnings
 * list into a single categorization. Used by the headline counts row so
 * "N nodes need manual review" includes the per-format expression fallbacks
 * + missing generators + unsupported tools — otherwise the top counts say
 * "0 need review" while the per-format tab lists 7 items, which contradicts.
 *
 * Deduplicates by (kind, nodeId, generator?) so the same node appearing in
 * three format warning lists is counted once.
 */
export function categorizeAcrossAllFormats(
  workflowWarnings: ReadonlyArray<string>,
  formatWarningsLists: ReadonlyArray<ReadonlyArray<string>>,
): CategorizedWarnings {
  const all: ParsedWarning[] = [...parseWarnings(workflowWarnings)];
  for (const fmtWarnings of formatWarningsLists) {
    all.push(...parseWarnings(fmtWarnings));
  }
  // Dedup by stable key — same node + same kind from multiple formats counts
  // once. Generator is included because "missing_generator for X in DLT" and
  // "missing_generator for X in SQL" are distinct user-actionable items.
  const seen = new Set<string>();
  const deduped: ParsedWarning[] = [];
  for (const w of all) {
    const key = `${w.kind}|${w.nodeId ?? "?"}|${w.generator ?? "?"}|${w.tool ?? "?"}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(w);
  }
  return categorizeWarnings(deduped);
}

/**
 * Build the set of node ids that sit in a disconnected component containing
 * an unsupported node. These are the nodes that "break" the pipeline — useful
 * for the `cannot_deploy` deploy-status decision.
 */
export function nodesInBrokenComponents(
  parsed: ReadonlyArray<ParsedWarning>,
): Set<number> {
  const broken = new Set<number>();
  const components = parsed
    .filter((w) => w.kind === "disconnected_components")
    .flatMap((w) => w.components ?? []);
  if (components.length === 0) return broken;
  const unsupportedIds = new Set(
    parsed
      .filter((w) => w.kind === "unsupported_tool" && w.nodeId !== undefined)
      .map((w) => w.nodeId as number),
  );
  for (const comp of components) {
    if (comp.some((id) => unsupportedIds.has(id))) {
      for (const id of comp) broken.add(id);
    }
  }
  return broken;
}
