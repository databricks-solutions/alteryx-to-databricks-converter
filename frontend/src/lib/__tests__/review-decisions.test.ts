import { describe, expect, it } from "vitest";
import type { ReviewNode, ReviewSession } from "@/lib/api";
import { codeHash, restore, sameDecisions, sourceKey, toRecord } from "@/lib/review-decisions";

function node(id: number, code: string): ReviewNode {
  return {
    node_id: id,
    tool_type: "Formula",
    annotation: null,
    position: [0, 0],
    status: "needs_review",
    confidence: 0.5,
    generated_code: code,
    warnings: [],
    conversion_method: "deterministic",
  } as unknown as ReviewNode;
}

function session(nodes: ReviewNode[], fmt = "pyspark"): ReviewSession {
  return { workflow_name: "wf", output_format: fmt, nodes, edges: [] } as unknown as ReviewSession;
}

describe("review decisions", () => {
  const s = session([node(1, "# Step 1\ndf_1 = x"), node(2, "# Step 2\ndf_2 = df_1")]);

  it("saves only decided steps, with a hash of the code they were made on", () => {
    const rec = toRecord(s, {
      1: { decision: "pending", editedCode: null },
      2: { decision: "edited", editedCode: "# Step 2\ndf_2 = df_1.limit(1)", source: "ai" },
    });
    expect(Object.keys(rec.nodes)).toEqual(["2"]);
    expect(rec.nodes["2"]).toEqual({
      decision: "edited",
      code: "# Step 2\ndf_2 = df_1.limit(1)",
      source: "ai",
      base: codeHash("# Step 2\ndf_2 = df_1"),
    });
    expect(rec.output_format).toBe("pyspark");
  });

  it("restores a decision while the step's code is unchanged", () => {
    const rec = toRecord(s, { 2: { decision: "accepted", editedCode: null, source: null } });
    const back = restore(s, rec);
    expect(back.restored).toBe(1);
    expect(back.stale).toBe(0);
    expect(back.decisions[2]).toEqual({ decision: "accepted", editedCode: null, source: null });
  });

  it("drops a decision when the step's code changed, or the format differs", () => {
    const rec = toRecord(s, { 2: { decision: "rejected", editedCode: null } });
    const changed = session([node(1, "# Step 1\ndf_1 = x"), node(2, "# Step 2\ndf_2 = df_1  # new")]);
    expect(restore(changed, rec)).toEqual({ decisions: {}, restored: 0, stale: 1 });
    expect(restore(session(s.nodes, "sql"), rec).restored).toBe(0);
    expect(restore(s, null).restored).toBe(0);
  });

  it("compares decision sets without pending ones", () => {
    expect(sameDecisions({ 1: { decision: "pending", editedCode: null } }, {})).toBe(true);
    expect(sameDecisions({ 1: { decision: "accepted", editedCode: null } }, {})).toBe(false);
  });
});

describe("sourceKey", () => {
  it("is the same for equal sources, different for another file", () => {
    const a = new File(["x"], "a.yxmd", { lastModified: 1 });
    expect(sourceKey({ file: a })).toBe(sourceKey({ file: a, macros: [] }));
    expect(sourceKey({ projectId: "p", workflowId: "w" })).toBe(sourceKey({ projectId: "p", workflowId: "w" }));
    expect(sourceKey({ file: new File(["xy"], "a.yxmd", { lastModified: 1 }) })).not.toBe(sourceKey({ file: a }));
  });
});
