import { describe, it, expect } from "vitest";
import { csvField, analysisToCsv } from "../csv";
import type { WorkflowAnalysis } from "../api";

describe("csvField (RFC-4180 quoting)", () => {
  it("quotes plain values", () => {
    expect(csvField("abc")).toBe('"abc"');
    expect(csvField(42)).toBe('"42"');
  });

  it("doubles embedded quotes", () => {
    expect(csvField('say "hi"')).toBe('"say ""hi"""');
  });

  it("keeps commas and newlines inside the quoted field", () => {
    // A comma must not split the field; a newline must not add a row.
    expect(csvField("a,b")).toBe('"a,b"');
    expect(csvField("line1\nline2")).toBe('"line1\nline2"');
  });
});

describe("analysisToCsv", () => {
  const wf = (name: string): WorkflowAnalysis => ({
    file_name: "f.yxmd",
    workflow_name: name,
    node_count: 1,
    connection_count: 0,
    coverage_percentage: 100,
    complexity_score: 1,
    complexity_level: "Low",
    migration_priority: "Low",
    estimated_effort: "1h",
    tool_types: ["Input"],
    unsupported_types: [],
    warnings: [],
  });

  it("does not let a comma in a workflow name shift columns", () => {
    const csv = analysisToCsv([wf("Sales, EMEA")]);
    const [header, row] = csv.split("\n");
    // Header and the row must have the same number of RFC-4180 fields.
    const countFields = (line: string) => (line.match(/","|^"|"$/g) || []).length;
    expect(row.startsWith('"Sales, EMEA"')).toBe(true);
    // The embedded comma is inside quotes, so splitting on unquoted commas keeps columns aligned.
    expect(header.split('","').length).toBe(row.split('","').length);
    expect(countFields(header)).toBeGreaterThan(0);
  });

  it("escapes quotes and newlines in a workflow name", () => {
    const csv = analysisToCsv([wf('Weird"\nName')]);
    const row = csv.split("\n").slice(1).join("\n"); // the name embeds a newline
    expect(row).toContain('"Weird""');
  });
});
