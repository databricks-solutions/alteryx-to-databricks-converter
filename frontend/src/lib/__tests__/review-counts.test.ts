import { describe, expect, it } from "vitest";
import { categorizeAcrossAllFormats } from "@/lib/warning-parsing";
import { placeholderCostLabels, usesPlaceholderCosts } from "@/routes/savings";
import type { CostAssumptions } from "@/lib/api";

describe("converted-but-worth-checking count", () => {
  it("doesn't count a tool that wasn't converted", () => {
    const c = categorizeAcrossAllFormats(
      ["Unsupported node 30 (MakeColumns): No converter for tool type: MakeColumns"],
      [
        ["Unsupported node 30 (MakeColumns): No converter for tool type: MakeColumns"],
        ["Input node 24: path '..\\DATA\\x.xlsx' is a local/UNC path; migrate it to cloud storage"],
        ["Formula expression fallback for node 7: IIF"],
      ],
    );
    expect(c.unsupported.map((w) => w.nodeId)).toEqual([30]);
    // 24 and 7 were converted but carry something to check; 30 is "not converted", not both.
    expect([...c.checkNodeIds].sort()).toEqual([24, 7].sort());
    expect(c.manualReviewNodeCount).toBe(3);
  });
});

describe("usesPlaceholderCosts", () => {
  const defaults = {
    currency: "USD",
    designer_seats: 10,
    designer_cost_per_seat_year: 5000,
    server_licenses: 1,
    server_cost_per_license_year: 50000,
    developer_hourly_rate: 100,
    automation_factor: null,
    review_hours_per_workflow: 1,
    dbu_price: 0.55,
    dbu_per_workflow_run: 2,
    runs_per_month: 30,
    annual_maintenance_savings: 15000,
    analysis_horizon_years: 3,
    hour_anchors: {},
  } satisfies CostAssumptions;

  it("is true while the money inputs are the placeholders", () => {
    // Changing a non-money input (the horizon) doesn't make the costs real.
    expect(usesPlaceholderCosts({ ...defaults, analysis_horizon_years: 5 }, defaults)).toBe(true);
  });

  it("is false only once every money input is the user's", () => {
    // One entered figure next to placeholder costs still gives a made-up ROI.
    expect(usesPlaceholderCosts({ ...defaults, designer_seats: 42 }, defaults)).toBe(true);
    expect(placeholderCostLabels({ ...defaults, designer_seats: 42 }, defaults)).not.toContain("Designer seats");
    const allMine = {
      ...defaults,
      designer_seats: 42,
      designer_cost_per_seat_year: 4000,
      server_licenses: 3,
      server_cost_per_license_year: 70000,
      developer_hourly_rate: 140,
      annual_maintenance_savings: 20000,
      dbu_price: 0.6,
    };
    expect(usesPlaceholderCosts(allMine, defaults)).toBe(false);
  });
});
