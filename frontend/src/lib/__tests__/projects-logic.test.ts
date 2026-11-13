import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import { isProjectsNotConfigured } from "@/hooks/use-project";
import { slugify } from "@/lib/files";
import { useEstateStore } from "@/stores/estate";

describe("isProjectsNotConfigured", () => {
  const notConfigured =
    "Saved projects need a database, and this server doesn't have one configured. The app still works with a project kept in the browser.";

  it("is true only for the server's no-database 503", () => {
    expect(isProjectsNotConfigured(new ApiError(notConfigured, 503))).toBe(true);
  });

  it("is false when the database is configured but down, or for other errors", () => {
    expect(isProjectsNotConfigured(new ApiError("Saved projects are temporarily unavailable", 503))).toBe(false);
    expect(isProjectsNotConfigured(new ApiError(notConfigured, 500))).toBe(false);
    expect(isProjectsNotConfigured(new Error(notConfigured))).toBe(false);
    expect(isProjectsNotConfigured(null)).toBe(false);
  });
});

describe("slugify", () => {
  it("makes names safe for download file names", () => {
    expect(slugify("Finance estate / Q1")).toBe("Finance_estate_Q1");
    expect(slugify("売上")).toBe("project");
  });
});

describe("estate result cache", () => {
  beforeEach(() => useEstateStore.setState({ byProject: {} }));

  it("keeps a bounded number of projects, dropping the least recently used", () => {
    const save = useEstateStore.getState().saveResult;
    for (let i = 0; i < 20; i++) save(`p${i}`, "readiness", {} as never, "sig");
    const ids = Object.keys(useEstateStore.getState().byProject);
    expect(ids.length).toBe(12);
    expect(ids).toContain("p19");
    expect(ids).not.toContain("p0");
  });

  it("remembers the inputs a result was computed with", () => {
    useEstateStore.getState().saveResult("p", "savings", {} as never, "sig", { designer_seats: 7 });
    expect(useEstateStore.getState().byProject.p.savings?.args).toEqual({ designer_seats: 7 });
  });
});
