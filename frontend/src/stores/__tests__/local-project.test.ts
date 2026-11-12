import { beforeEach, describe, expect, it } from "vitest";
import { isAtOrPast, useLocalProjectStore } from "@/stores/local-project";

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
