import { afterEach, describe, expect, it, vi } from "vitest";
import { api, isMacroFile } from "@/lib/api";

/** Capture the FormData the next API call sends. */
function captureForm(): () => FormData {
  let sent: FormData | null = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      sent = init?.body as FormData;
      return new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return () => sent!;
}

const file = (name: string) => new File(["<x/>"], name);

afterEach(() => vi.unstubAllGlobals());

describe("isMacroFile", () => {
  it("matches .yxmc in any case and nothing else", () => {
    expect(isMacroFile("Cleanse.yxmc")).toBe(true);
    expect(isMacroFile("CLEANSE.YXMC")).toBe(true);
    expect(isMacroFile("main.yxmd")).toBe(false);
    expect(isMacroFile("pkg.yxzp")).toBe(false);
  });
});

describe("single-workflow calls", () => {
  it("send a saved project's workflow by reference, with no file", async () => {
    const form = captureForm();
    await api.convert({ projectId: "p1", workflowId: "w1" });
    expect(form().get("project_id")).toBe("p1");
    expect(form().get("workflow_id")).toBe("w1");
    expect(form().get("file")).toBeNull();
    expect(form().getAll("macros")).toEqual([]);
  });

  it("send a session workflow with the session's macros", async () => {
    const form = captureForm();
    await api.review({ file: file("main.yxmd"), macros: [file("A.yxmc"), file("B.yxmc")] });
    expect((form().get("file") as File).name).toBe("main.yxmd");
    expect(form().getAll("macros").map((m) => (m as File).name)).toEqual(["A.yxmc", "B.yxmc"]);
    expect(form().get("project_id")).toBeNull();
  });

  it("no longer send an expand_macros option", async () => {
    const form = captureForm();
    await api.advise({ projectId: "p1", workflowId: "w1" }, "azure");
    expect(form().get("expand_macros")).toBeNull();
    expect(form().get("cloud")).toBe("azure");
  });
});

describe("batch convert of a session project", () => {
  it("sends the selection as files and the other macros separately", async () => {
    const form = captureForm();
    await api.convertBatch({ files: [file("main.yxmd")], macros: [file("A.yxmc")] });
    expect(form().getAll("files").map((f) => (f as File).name)).toEqual(["main.yxmd"]);
    expect(form().getAll("macros").map((f) => (f as File).name)).toEqual(["A.yxmc"]);
  });
});
