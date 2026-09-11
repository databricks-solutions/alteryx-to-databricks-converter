// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge } from "../badge";

describe("Badge", () => {
  it("renders its children", () => {
    render(<Badge>Ready</Badge>);
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("uses the theme-aware AA-contrast foreground token per variant", () => {
    render(<Badge variant="success">OK</Badge>);
    // The contrast fix routes text through --badge-success-fg (dark in light mode,
    // light in dark mode) rather than the raw low-contrast success color.
    expect(screen.getByText("OK").className).toContain("text-[var(--badge-success-fg)]");
  });

  it("defaults to the default variant when none is given", () => {
    render(<Badge>Info</Badge>);
    expect(screen.getByText("Info").className).toContain("var(--ring)");
  });
});
