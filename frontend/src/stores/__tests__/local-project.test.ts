import { beforeEach, describe, expect, it } from "vitest";
import { isLocalProjectId, useLocalProjectStore } from "@/stores/local-project";
import { isAtOrPast } from "@/lib/stages";

const file = (name: string, body = "<x/>") => new File([body], name, { type: "application/xml" });
const store = () => useLocalProjectStore.getState();

describe("session-only project", () => {
  beforeEach(() => store().clear());

  it("creates a project from files, sorted by name", () => {
    store().create("Estate", [file("b.yxmd"), file("a.yxmd")]);
    expect(store().name).toBe("Estate");
    expect(store().workflows.map((w) => w.file_name)).toEqual(["a.yxmd", "b.yxmd"]);
    expect(store().workflows.every((w) => w.stage === "uploaded")).toBe(true);
  });

  it("re-adding a file name replaces that workflow and starts it over", () => {
    store().create("Estate", [file("a.yxmd")]);
    const id = store().workflows[0].id;
    store().advance(() => true, "converted");
    store().add([file("a.yxmd", "<v2/>")]);
    expect(store().workflows).toHaveLength(1);
    expect(store().workflows[0].id).toBe(id);
    expect(store().workflows[0].stage).toBe("uploaded");
  });

  it("only moves stages forward", () => {
    store().create("Estate", [file("a.yxmd")]);
    store().advance(() => true, "deployed");
    store().advance(() => true, "converted");
    expect(store().workflows[0].stage).toBe("deployed");
    store().setConversion("a.yxmd", { coverage: 80 });
    expect(store().workflows[0].stage).toBe("deployed");
    expect(store().workflows[0].conversion?.coverage).toBe(80);
  });

  it("gives every new session project its own id", () => {
    const first = store().create("A", [file("a.yxmd")]);
    const second = store().create("B", [file("a.yxmd")]);
    expect(first).not.toBe(second);
    expect(isLocalProjectId(first)).toBe(true);
    expect(isLocalProjectId("00000000-0000-0000-0000-000000000000")).toBe(false);
    expect(store().id).toBe(second);
  });

  it("re-adding a file clears what was computed for the old version", () => {
    store().create("Estate", [file("a.yxmd")]);
    store().setAnalysis({ "a.yxmd": { coverage_percentage: 50 } });
    store().setConversion("a.yxmd", { coverage: 50 });
    store().add([file("a.yxmd", "<v2/>")]);
    expect(store().workflows[0].analysis).toBeNull();
    expect(store().workflows[0].conversion).toBeNull();
  });

  it("removes a workflow", () => {
    store().create("Estate", [file("a.yxmd"), file("b.yxmd")]);
    store().remove(store().workflows[0].id);
    expect(store().workflows.map((w) => w.file_name)).toEqual(["b.yxmd"]);
  });
});

describe("isAtOrPast", () => {
  it("orders the lifecycle", () => {
    expect(isAtOrPast("reviewed", "converted")).toBe(true);
    expect(isAtOrPast("assessed", "converted")).toBe(false);
    expect(isAtOrPast("converted", "converted")).toBe(true);
  });
});
