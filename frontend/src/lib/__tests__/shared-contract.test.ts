/**
 * TypeScript half of the cross-language warning/deploy-status contract.
 *
 * `warning-parsing.ts` and `deploy-status.ts` are hand-ports of
 * `src/a2d/observability/warning_categorization.py` and `deploy_status.py`. Two
 * implementations of the same rules will drift, and drift is user-visible: the UI
 * would show a different deploy verdict than the CLI for the same workflow.
 *
 * These tests and their Python counterpart
 * (`tests/unit/observability/test_shared_contract.py`) assert against the SAME
 * fixture, so a one-sided change fails the other language's suite.
 *
 * Fixture: tests/fixtures/shared/warning_parsing_cases.json
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { parseWarning } from "../warning-parsing";
import { deriveDeployStatus } from "../deploy-status";
import type { ConversionResult, FormatResult } from "../api";

interface WarningCase {
  name: string;
  raw: string;
  expect: {
    kind: string;
    severity: string;
    node_id?: number | null;
    tool?: string;
  };
}

interface DeployCase {
  name: string;
  coverage: number;
  confidence: number;
  formats_status: Record<string, string>;
  workflow_warnings: string[];
  best_format_warnings: string[];
  expect: string;
}

const FIXTURE = join(__dirname, "../../../../tests/fixtures/shared/warning_parsing_cases.json");
const cases = JSON.parse(readFileSync(FIXTURE, "utf8")) as {
  warning_cases: WarningCase[];
  deploy_status_cases: DeployCase[];
};

describe("warning parsing matches the shared contract", () => {
  it.each(cases.warning_cases)("$name", (testCase) => {
    const parsed = parseWarning(testCase.raw);

    expect(parsed.kind).toBe(testCase.expect.kind);
    expect(parsed.severity).toBe(testCase.expect.severity);

    if (testCase.expect.node_id !== undefined) {
      // Python uses snake_case `node_id` and null; TS uses `nodeId` and undefined.
      const expected = testCase.expect.node_id;
      if (expected === null) {
        expect(parsed.nodeId).toBeUndefined();
      } else {
        expect(parsed.nodeId).toBe(expected);
      }
    }
    if (testCase.expect.tool !== undefined) {
      expect(parsed.tool).toBe(testCase.expect.tool);
    }
  });
});

/** Build the minimal ConversionResult that deriveDeployStatus reads. */
function buildResult(testCase: DeployCase): ConversionResult {
  const formats: Record<string, FormatResult> = {};
  for (const [formatId, status] of Object.entries(testCase.formats_status)) {
    const isBest = formatId === "pyspark";
    formats[formatId] = {
      format: formatId as FormatResult["format"],
      status: status as FormatResult["status"],
      files: [],
      stats: { coverage_percentage: testCase.coverage },
      warnings: isBest ? testCase.best_format_warnings : [],
      confidence: {
        overall: testCase.confidence,
        level: "n/a",
        dimensions: [],
      },
      error: null,
    };
  }

  return {
    workflow_name: testCase.name,
    node_count: 1,
    edge_count: 0,
    warnings: testCase.workflow_warnings,
    dag_data: null,
    best_format: "pyspark",
    formats,
    coverage: testCase.coverage,
  };
}

describe("deploy status matches the shared contract", () => {
  it.each(cases.deploy_status_cases)("$name", (testCase) => {
    expect(deriveDeployStatus(buildResult(testCase))).toBe(testCase.expect);
  });
});

describe("the fixture itself is usable", () => {
  it("has cases on both sides", () => {
    expect(cases.warning_cases.length).toBeGreaterThanOrEqual(5);
    expect(cases.deploy_status_cases.length).toBeGreaterThanOrEqual(5);
  });
});
