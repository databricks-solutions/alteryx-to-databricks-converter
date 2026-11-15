import { describe, expect, it } from "vitest";
import { sharedTools, whatWillHappen } from "@/lib/ai-estimate";

const status = {
  enabled: true,
  model: "databricks-claude-opus-5-5",
  parallel: 4,
  step_seconds: { median: 4.2, p90: 10.9 },
};
const steps = (...tools: (string | null)[]) => tools.map((tool_type) => ({ tool_type }));

describe("whatWillHappen", () => {
  it("names the model, the steps and a time range", () => {
    expect(whatWillHappen(steps("Message"), status)).toBe(
      "This sends 1 step to databricks-claude-opus-5-5, 4 at a time. It usually takes about 5 seconds to 10 seconds.",
    );
  });

  it("adds a round for the shared helpers of tools several steps use", () => {
    const text = whatWillHappen(steps("MakeColumns", "MakeColumns", "Input", "Input", "Message"), status);
    expect(text).toContain("one shared helper for MakeColumns, Input");
    // 5 steps in 2 rounds of 4, plus 1 helper round: 3 x 4.2 s to 3 x 10.9 s.
    expect(text).toContain("about 15 seconds to 35 seconds");
  });

  it("switches to minutes for a long run", () => {
    expect(whatWillHappen(steps(...Array(40).fill(null)), status)).toContain("to 2 minutes");
  });
});

describe("sharedTools", () => {
  it("lists tools used by two or more steps", () => {
    expect(sharedTools(steps("A", "B", "A", null, null))).toEqual(["A"]);
  });
});
