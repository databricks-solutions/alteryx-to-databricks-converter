/**
 * Pure decision function for the headline "deploy readiness" banner shown at
 * the top of the Convert page.
 *
 * Rule table (derived directly from a `ConversionResult`):
 *
 *   ┌─────────────────┬───────────────────────────────────────────────────────┐
 *   │ "ready"         │ ALL of:                                               │
 *   │                 │   - every requested format reports `status="success"` │
 *   │                 │   - best-format coverage ≥ 95 %                       │
 *   │                 │   - best-format confidence ≥ 80 / 100                 │
 *   │                 │   - zero "Unsupported node ..." warnings              │
 *   │                 │   - zero "No <X> generator for ..." warnings          │
 *   ├─────────────────┼───────────────────────────────────────────────────────┤
 *   │ "needs_review"  │ Generator(s) succeeded, BUT at least one of:          │
 *   │                 │   - any missing-visitor / expression-fallback warning │
 *   │                 │   - 60 ≤ confidence < 80                              │
 *   │                 │   - 70 ≤ coverage < 95                                │
 *   │                 │ AND we don't already qualify for "cannot_deploy".     │
 *   ├─────────────────┼───────────────────────────────────────────────────────┤
 *   │ "cannot_deploy" │ ANY of:                                               │
 *   │                 │   - any format with status="failed"                   │
 *   │                 │   - best-format coverage < 70 %                       │
 *   │                 │   - an unsupported node sits in a disconnected        │
 *   │                 │     component (i.e. it actually breaks the dataflow)  │
 *   └─────────────────┴───────────────────────────────────────────────────────┘
 *
 * Boundary cases (informally; treat the literal numbers as the source of
 * truth — these are inclusive lower bounds unless otherwise noted):
 *
 *   - coverage = 95.0, confidence = 80, no warnings    → "ready"
 *   - coverage = 94.9, confidence = 80, no warnings    → "needs_review"
 *   - coverage = 70.0, confidence = 95                 → "needs_review"
 *   - coverage = 69.9                                  → "cannot_deploy"
 *   - confidence = 60.0                                → "needs_review"
 *   - confidence = 59.9                                → "needs_review"
 *     (low confidence alone never escalates to "cannot_deploy" —
 *     coverage / failed formats / unsupported-in-dataflow do that)
 *   - any format failed (e.g. SQL generator threw)    → "cannot_deploy"
 *   - 1 unsupported node, NOT in the main flow         → "needs_review"
 *     (placeholder is harmless if it's a side branch; the warning still
 *     surfaces in the UI)
 *   - 1 unsupported node IS in the main flow           → "cannot_deploy"
 *   - All four formats succeed but every coverage = 0  → "cannot_deploy"
 *     (0 < 70 satisfies the "<70%" rule)
 *   - best_format = "" (everything failed at the generator level)
 *     → "cannot_deploy" (every format's status is "failed")
 *
 * The function is intentionally pure / no React imports so it can be reused
 * elsewhere (batch summary, history panel) without dragging UI state along.
 */

import type { ConversionResult } from "@/lib/api";
import {
  categorizeForFormat,
  nodesInBrokenComponents,
  parseWarnings,
} from "@/lib/warning-parsing";

/** Three-tier deploy readiness signal. */
export type DeployStatus = "ready" | "needs_review" | "cannot_deploy";

/** Threshold constants, exported so they're greppable in code review. */
export const DEPLOY_THRESHOLDS = {
  /** Inclusive minimum coverage % for "ready". */
  READY_COVERAGE: 95,
  /** Inclusive minimum confidence (out of 100) for "ready". */
  READY_CONFIDENCE: 80,
  /** Inclusive minimum coverage % to stay above "cannot_deploy". */
  REVIEW_COVERAGE_MIN: 70,
  /** Inclusive minimum confidence (out of 100) to stay above the lower band. */
  REVIEW_CONFIDENCE_MIN: 60,
} as const;

/**
 * Pure deploy-status decision from a `ConversionResult`.
 *
 * @param response The raw `/api/convert` response (multi-format).
 */
export function deriveDeployStatus(
  response: ConversionResult,
): DeployStatus {
  const formats = response.formats ?? {};
  const formatEntries = Object.values(formats);

  // ── 1. Cannot deploy: any format outright failed ───────────────────────
  const anyFailed = formatEntries.some((fr) => fr.status === "failed");
  if (anyFailed) return "cannot_deploy";

  // ── 2. Cannot deploy: an unsupported node sits in a broken component ───
  // We parse workflow-level warnings (these contain the disconnected
  // component note + the unsupported-tool entries).
  const parsedWorkflowWarnings = parseWarnings(response.warnings ?? []);
  const broken = nodesInBrokenComponents(parsedWorkflowWarnings);
  if (broken.size > 0) return "cannot_deploy";

  const bestFormat = response.best_format;
  const bestFormatResult = bestFormat ? formats[bestFormat] : undefined;

  // No best format / no entries means every generator must have failed.
  if (!bestFormatResult || bestFormatResult.status !== "success") {
    return "cannot_deploy";
  }

  // ── 3. Pull the headline numbers from the best format. ─────────────────
  const coverageRaw = bestFormatResult.stats?.coverage_percentage;
  const coverage = typeof coverageRaw === "number" ? coverageRaw : null;
  const confidence = bestFormatResult.confidence?.overall ?? null;

  // ── 4. Cannot deploy: coverage too low. ────────────────────────────────
  if (coverage !== null && coverage < DEPLOY_THRESHOLDS.REVIEW_COVERAGE_MIN) {
    return "cannot_deploy";
  }

  // ── 5. Combine workflow + best-format warnings, count categories. ──────
  const cats = categorizeForFormat(
    response.warnings ?? [],
    bestFormatResult.warnings ?? [],
  );
  const unsupportedCount = cats.unsupported.length;
  const reviewCount = cats.review.length; // missing_generator + expression_fallback

  // Unsupported tools without a connector are a manual-rewrite signal —
  // we already escalated "in main flow" cases to cannot_deploy above, but
  // even side-branch unsupported nodes block "ready".
  const hasManualWork = unsupportedCount > 0 || reviewCount > 0;

  // ── 6. Ready: clean, high-coverage, high-confidence. ───────────────────
  if (
    !hasManualWork &&
    coverage !== null &&
    coverage >= DEPLOY_THRESHOLDS.READY_COVERAGE &&
    confidence !== null &&
    confidence >= DEPLOY_THRESHOLDS.READY_CONFIDENCE
  ) {
    return "ready";
  }

  // ── 7. Otherwise: needs review. ────────────────────────────────────────
  return "needs_review";
}
